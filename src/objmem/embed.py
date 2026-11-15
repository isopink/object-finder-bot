"""Image and text embedders.

ClipEmbedder runs OpenCLIP (ViT-B-32, laion2b_s34b_b79k, FP16 on CUDA) and is
the port of the `Clip` class in the old vision/jetson_find_object.py.
FakeEmbedder needs only numpy and is deterministic, for tests and `--fake` runs.

torch, open_clip and PIL are imported inside ClipEmbedder so that
`import objmem.embed` works on a plain PC.
"""
import hashlib
from collections import OrderedDict
from typing import Dict, List, Optional, Tuple

import numpy as np

DIM = 512


def _normalize(v: np.ndarray) -> np.ndarray:
    v = np.asarray(v, dtype=np.float32)
    if v.ndim == 1:
        n = float(np.linalg.norm(v))
        return v / n if n > 0 else v
    n = np.linalg.norm(v, axis=1, keepdims=True)
    n[n == 0] = 1.0
    return (v / n).astype(np.float32)


# ---------------------------------------------------------------- CLIP
class ClipEmbedder:
    """OpenCLIP image and text encoder.

    device=None picks "cuda" when available, else "cpu". FP16 is used only on CUDA.
    Images are encoded in batches of `batch_size` to bound GPU memory.
    """

    def __init__(self, model: str = "ViT-B-32", pretrained: str = "laion2b_s34b_b79k",
                 fp16: bool = True, device: Optional[str] = None, batch_size: int = 32):
        import torch
        import open_clip

        if device is None:
            device = "cuda" if torch.cuda.is_available() else "cpu"
        self.device = device
        self.fp16 = bool(fp16) and device.startswith("cuda")
        self.batch_size = int(batch_size)
        self.model_name = model
        self.pretrained = pretrained
        self._torch = torch
        net, _, preprocess = open_clip.create_model_and_transforms(model, pretrained=pretrained)
        self.tokenizer = open_clip.get_tokenizer(model)
        net = net.to(device).eval()
        if self.fp16:
            net = net.half()
        self.model = net
        self.preprocess = preprocess

    def embed_images(self, images: List[np.ndarray]) -> np.ndarray:
        """List of RGB uint8 crops -> (N, 512) L2-normalized float32."""
        from PIL import Image

        torch = self._torch
        if len(images) == 0:
            return np.zeros((0, DIM), dtype=np.float32)
        out = []
        with torch.no_grad():
            for i in range(0, len(images), self.batch_size):
                chunk = images[i:i + self.batch_size]
                x = torch.stack([self.preprocess(Image.fromarray(np.ascontiguousarray(c))) for c in chunk])
                x = x.to(self.device)
                if self.fp16:
                    x = x.half()
                f = self.model.encode_image(x)
                f = f / f.norm(dim=-1, keepdim=True)
                out.append(f.float().cpu().numpy())
        return np.concatenate(out, axis=0).astype(np.float32)

    def embed_text(self, text: str) -> np.ndarray:
        """Sentence -> (512,) L2-normalized float32."""
        return self.embed_texts([text])[0]

    def embed_texts(self, texts: List[str]) -> np.ndarray:
        """Sentences -> (N, 512) L2-normalized float32."""
        torch = self._torch
        if len(texts) == 0:
            return np.zeros((0, DIM), dtype=np.float32)
        with torch.no_grad():
            f = self.model.encode_text(self.tokenizer(list(texts)).to(self.device))
            f = f / f.norm(dim=-1, keepdim=True)
            return f.float().cpu().numpy().astype(np.float32)


# ---------------------------------------------------------------- text cache
class CachedTextEmbedder:
    """Wraps an embedder and caches text embeddings (LRU, `maxsize` entries).

    Image embedding is passed through unchanged.
    """

    def __init__(self, embedder, maxsize: int = 512):
        self.inner = embedder
        self.maxsize = int(maxsize)
        self._cache = OrderedDict()  # type: OrderedDict
        self.hits = 0
        self.misses = 0

    def embed_images(self, images: List[np.ndarray]) -> np.ndarray:
        return self.inner.embed_images(images)

    def embed_text(self, text: str) -> np.ndarray:
        if text in self._cache:
            self._cache.move_to_end(text)
            self.hits += 1
            return self._cache[text]
        self.misses += 1
        vec = np.asarray(self.inner.embed_text(text), dtype=np.float32)
        vec.setflags(write=False)
        self._cache[text] = vec
        if len(self._cache) > self.maxsize:
            self._cache.popitem(last=False)
        return vec


# ---------------------------------------------------------------- fake
# Named colors the fake embedder understands. FakeCamera draws objects in these colors.
FAKE_COLORS = OrderedDict([
    ("red", (220, 30, 30)),
    ("green", (30, 180, 40)),
    ("blue", (30, 60, 220)),
    ("yellow", (230, 210, 30)),
    ("black", (20, 20, 20)),
    ("white", (240, 240, 240)),
])  # type: Dict[str, Tuple[int, int, int]]

# Background gray of FakeCamera; crops close to it embed as "nothing".
FAKE_BACKGROUND_RGB = (128, 128, 128)


def _hash_vec(key: str, dim: int = DIM) -> np.ndarray:
    seed = int.from_bytes(hashlib.sha256(key.encode("utf-8")).digest()[:8], "little")
    rng = np.random.RandomState(seed % (2 ** 32))
    return _normalize(rng.standard_normal(dim).astype(np.float32))


class FakeEmbedder:
    """Deterministic stand-in for CLIP. numpy only.

    There is one vector per named color in FAKE_COLORS and one "background" vector.

    - Text naming a color: 0.8 * color + 0.6 * hash(text), normalized.
      Other text (e.g. the background prompts): 0.8 * background + 0.6 * hash(text).
    - Image: the color closest to the mean of the crop's non-gray pixels, plus
      0.3 * background and a little noise from the crop size; a crop that is
      mostly background gray gets the background vector.

    So "a red mug" scores high against a red crop, the background prompts win
    on gray crops and on crops of other colors, and re-check behaves like CLIP
    on the FakeCamera frames.
    """

    def __init__(self, dim: int = DIM, color_weight: float = 0.8):
        self.dim = int(dim)
        self.color_weight = float(color_weight)
        self._color_vecs = {name: _hash_vec("color:" + name, self.dim) for name in FAKE_COLORS}
        self._bg_vec = _hash_vec("color:background", self.dim)

    def color_vector(self, name: str) -> np.ndarray:
        return self._color_vecs[name].copy()

    def embed_text(self, text: str) -> np.ndarray:
        words = set(text.lower().replace(",", " ").replace(".", " ").split())
        base = _hash_vec("text:" + text.strip().lower(), self.dim)
        w = self.color_weight
        rest = np.sqrt(max(0.0, 1.0 - w * w))
        for name in FAKE_COLORS:
            if name in words:
                return _normalize(w * self._color_vecs[name] + rest * base)
        return _normalize(w * self._bg_vec + rest * base)

    def _image_vec(self, img: np.ndarray) -> np.ndarray:
        img = np.asarray(img)
        if img.size == 0:
            return self._bg_vec.copy()
        px = img.reshape(-1, img.shape[-1])[:, :3].astype(np.float32)
        bg = np.array(FAKE_BACKGROUND_RGB, dtype=np.float32)
        fg = px[np.abs(px - bg).sum(axis=1) > 60]
        if len(fg) < 0.05 * len(px):
            vec = self._bg_vec
        else:
            mean = fg.mean(axis=0)
            names = list(FAKE_COLORS)
            dists = [float(np.abs(mean - np.array(FAKE_COLORS[n], dtype=np.float32)).sum()) for n in names]
            vec = self._color_vecs[names[int(np.argmin(dists))]] + 0.3 * self._bg_vec
        noise = _hash_vec("size:{}x{}".format(img.shape[0], img.shape[1]), self.dim)
        return _normalize(vec + 0.05 * noise)

    def embed_images(self, images: List[np.ndarray]) -> np.ndarray:
        if len(images) == 0:
            return np.zeros((0, self.dim), dtype=np.float32)
        return np.stack([self._image_vec(im) for im in images]).astype(np.float32)
