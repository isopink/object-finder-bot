"""Object detector adapters behind the `Detector` interface.

    make_detector("detectnet", network="ssd-mobilenet-v2", threshold=0.5)
    make_detector("yolo", model="yolov8n.pt", engine=None, conf=0.4)
    make_detector("owl", prompts=["a water bottle", ...], threshold=0.15)   # NanoOWL
    make_detector("fake")   # objmem.fakes.FakeDetector

Every detector takes an (H, W, 3) uint8 RGB numpy image and returns a list of
`RawBox` with integer (left, top, right, bottom) pixel boxes clipped to the
image. Hardware libraries (jetson_inference, jetson_utils, ultralytics, torch)
are imported only when a detector is built, so `import objmem.detectors` works
on any PC.
"""
import time
from typing import Any, Dict, List, Optional, Sequence

import numpy as np

from objmem.types import RawBox

DETECTOR_NAMES = ("detectnet", "yolo", "owl", "fake")


def clip_box(left: float, top: float, right: float, bottom: float, width: int, height: int):
    """Round a float box to ints inside a width x height image. None when it is empty."""
    l = int(max(0, min(width, round(float(left)))))
    t = int(max(0, min(height, round(float(top)))))
    r = int(max(0, min(width, round(float(right)))))
    b = int(max(0, min(height, round(float(bottom)))))
    if r <= l or b <= t:
        return None
    return (l, t, r, b)


def _to_numpy(x: Any) -> np.ndarray:
    """torch tensor (any device) or array-like -> numpy array."""
    if hasattr(x, "detach"):
        x = x.detach()
    if hasattr(x, "cpu"):
        x = x.cpu()
    if hasattr(x, "numpy"):
        return np.asarray(x.numpy())
    return np.asarray(x)


def _check_image(color: np.ndarray) -> None:
    if not isinstance(color, np.ndarray) or color.ndim != 3 or color.shape[2] < 3:
        raise ValueError("expected an (H, W, 3) RGB image, got {}".format(
            getattr(color, "shape", type(color))))


class _Timing(object):
    """Keeps an exponential moving average of detect() time, for FPS prints."""

    def __init__(self) -> None:
        self.last_ms = 0.0
        self.avg_ms = 0.0

    def add(self, seconds: float) -> None:
        ms = seconds * 1000.0
        self.last_ms = ms
        self.avg_ms = ms if self.avg_ms == 0.0 else 0.9 * self.avg_ms + 0.1 * ms

    def fps(self) -> float:
        return 1000.0 / self.avg_ms if self.avg_ms > 0 else 0.0


# ---------------------------------------------------------------- detectNet
class DetectNetDetector(object):
    """jetson_inference.detectNet (default SSD-Mobilenet-v2, COCO classes, TensorRT).

    The first run builds a TensorRT engine (a few minutes); later runs load the cache.
    `ignore` lists class names to drop (for example "person").
    """

    def __init__(self, network: str = "ssd-mobilenet-v2", threshold: float = 0.5,
                 ignore: Optional[Sequence[str]] = None, **_unused: Any) -> None:
        from jetson_inference import detectNet
        import jetson_utils
        self._utils = jetson_utils
        self.network = network
        self.threshold = float(threshold)
        self.ignore = set(s.lower() for s in (ignore or ()))
        self.net = detectNet(network, argv=[], threshold=self.threshold)
        self.timing = _Timing()

    def _convert(self, detections: Any, width: int, height: int) -> List[RawBox]:
        out = []  # type: List[RawBox]
        for d in detections:
            box = clip_box(d.Left, d.Top, d.Right, d.Bottom, width, height)
            if box is None:
                continue
            label = str(self.net.GetClassDesc(int(d.ClassID)))
            if label.lower() in self.ignore:
                continue
            out.append(RawBox(box=box, label=label, conf=float(d.Confidence)))
        return out

    def detect(self, color: np.ndarray) -> List[RawBox]:
        _check_image(color)
        t0 = time.time()
        rgb = np.ascontiguousarray(color[:, :, :3], dtype=np.uint8)
        cuda_img = self._utils.cudaFromNumpy(rgb)
        detections = self.net.Detect(cuda_img, overlay="none")
        out = self._convert(detections, rgb.shape[1], rgb.shape[0])
        self.timing.add(time.time() - t0)
        return out

    def detect_cuda(self, cuda_img: Any, overlay: str = "none") -> List[RawBox]:
        """Detect on a jetson_utils cudaImage (no copy). overlay e.g. "box,labels,conf"."""
        t0 = time.time()
        detections = self.net.Detect(cuda_img, overlay=overlay)
        out = self._convert(detections, int(cuda_img.width), int(cuda_img.height))
        self.timing.add(time.time() - t0)
        return out

    def fps(self) -> float:
        """Network FPS reported by detectNet (falls back to wall-clock timing)."""
        try:
            return float(self.net.GetNetworkFPS())
        except Exception:
            return self.timing.fps()


# ---------------------------------------------------------------- YOLO
class YoloDetector(object):
    """ultralytics YOLO. `model` is a .pt name or path; `engine` is an optional TensorRT
    .engine file (exported with `yolo export model=yolov8n.pt format=engine half=True`)
    that is used instead of `model` when given.

    ultralytics treats numpy input as BGR, so the RGB frame is flipped before predict.
    """

    def __init__(self, model: str = "yolov8n.pt", engine: Optional[str] = None,
                 conf: float = 0.4, imgsz: int = 640, device: Optional[str] = None,
                 half: bool = True, ignore: Optional[Sequence[str]] = None,
                 threshold: Optional[float] = None, **_unused: Any) -> None:
        from ultralytics import YOLO
        self.weights = engine or model
        self.is_engine = bool(engine)
        self.conf = float(threshold if threshold is not None else conf)
        self.imgsz = int(imgsz)
        self.device = device
        # A TensorRT engine has its precision baked in; only pass half for .pt models.
        self.half = bool(half) and not self.is_engine
        self.ignore = set(s.lower() for s in (ignore or ()))
        if self.is_engine:
            self.model = YOLO(self.weights, task="detect")
        else:
            self.model = YOLO(self.weights)
        self.timing = _Timing()

    def _names(self, result: Any) -> Dict[int, str]:
        names = getattr(result, "names", None) or getattr(self.model, "names", None) or {}
        if isinstance(names, (list, tuple)):
            names = dict(enumerate(names))
        return names

    def detect(self, color: np.ndarray) -> List[RawBox]:
        _check_image(color)
        t0 = time.time()
        height, width = color.shape[:2]
        bgr = np.ascontiguousarray(color[:, :, 2::-1], dtype=np.uint8)
        kwargs = {"conf": self.conf, "imgsz": self.imgsz, "verbose": False}
        if self.device is not None:
            kwargs["device"] = self.device
        if self.half:
            kwargs["half"] = True
        results = self.model.predict(bgr, **kwargs)
        out = []  # type: List[RawBox]
        if results:
            result = results[0]
            boxes = getattr(result, "boxes", None)
            if boxes is not None and len(boxes) > 0:
                xyxy = _to_numpy(boxes.xyxy).reshape(-1, 4)
                confs = _to_numpy(boxes.conf).reshape(-1)
                classes = _to_numpy(boxes.cls).reshape(-1)
                names = self._names(result)
                for (l, t, r, b), c, k in zip(xyxy, confs, classes):
                    box = clip_box(l, t, r, b, width, height)
                    if box is None:
                        continue
                    label = str(names.get(int(k), str(int(k))))
                    if label.lower() in self.ignore:
                        continue
                    out.append(RawBox(box=box, label=label, conf=float(c)))
        self.timing.add(time.time() - t0)
        return out

    def fps(self) -> float:
        return self.timing.fps()


# ---------------------------------------------------------------- NanoOWL
# Things that stand on desks and floors in a classroom. OWL-ViT finds any
# phrase, so this list (not a fixed class set) decides what gets proposed.
OWL_DEFAULT_PROMPTS = (
    "a banana", "an apple", "an orange", "a water bottle", "a cup", "a mug",
    "a backpack", "a bag", "a laptop", "a cell phone", "a book", "a box",
    "an umbrella", "a hat", "a wallet", "a key", "a remote control", "a toy",
    "a keyboard", "a computer mouse", "a scissors", "a teddy bear", "a shoe", "a ball",
)
OWL_DEFAULT_ENGINE = "~/nanoowl/data/owl_image_encoder_patch32.engine"


def _box_iou(a: Sequence[int], b: Sequence[int]) -> float:
    iw = min(a[2], b[2]) - max(a[0], b[0])
    ih = min(a[3], b[3]) - max(a[1], b[1])
    if iw <= 0 or ih <= 0:
        return 0.0
    inter = float(iw * ih)
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def nms_boxes(boxes: List[RawBox], iou: float = 0.7, max_boxes: int = 0) -> List[RawBox]:
    """Highest conf first; drop a box that overlaps a kept one by more than `iou`
    whatever its label (OWL often returns one object under two phrases)."""
    kept = []  # type: List[RawBox]
    for b in sorted(boxes, key=lambda x: -x.conf):
        if all(_box_iou(b.box, k.box) <= iou for k in kept):
            kept.append(b)
            if max_boxes and len(kept) >= max_boxes:
                break
    return kept


class OwlDetector(object):
    """NVIDIA-AI-IOT/nanoowl (OWL-ViT B/32, TensorRT image encoder): open-vocabulary
    boxes for a list of text prompts. Finds things the COCO detectors miss (a clear
    plastic bottle, a cardboard box: 2026-11-24, C920 and D455, about 77 ms/frame).

    `engine` is the image encoder built once on the Jetson:
      python -m nanoowl.build_image_encoder_engine data/owl_image_encoder_patch32.engine
    (or ONNX export + trtexec --fp16 when that runs out of memory). Without an engine
    nanoowl runs the encoder in PyTorch (slower). Labels are the prompts without the
    leading article ("water bottle"). `threshold` is OWL's score, which is lower than
    detectNet's: 0.1-0.2 keeps real objects, 0.3+ keeps only clear ones.

    `slim` (default: the OFB_OWL_SLIM environment variable, off) frees the PyTorch
    parts that are not used after start-up; see `slim_owl_predictor`. The prompts are
    then fixed for the life of the detector.
    """

    def __init__(self, prompts: Optional[Sequence[str]] = None, engine: Optional[str] = OWL_DEFAULT_ENGINE,
                 threshold: float = 0.15, model: str = "google/owlvit-base-patch32",
                 nms_iou: float = 0.7, max_boxes: int = 20,
                 ignore: Optional[Sequence[str]] = None, slim: Optional[bool] = None,
                 **_unused: Any) -> None:
        import os
        import sys
        try:
            from nanoowl.owl_predictor import OwlPredictor
        except ImportError:
            # `pip install -e .` may have gone to another env: use the clone directly.
            src = os.path.expanduser(os.environ.get("OFB_NANOOWL_DIR", "~/nanoowl"))
            if os.path.isdir(os.path.join(src, "nanoowl")) and src not in sys.path:
                sys.path.insert(0, src)
            from nanoowl.owl_predictor import OwlPredictor
        from PIL import Image
        self._Image = Image
        self.prompts = [p.strip() for p in (prompts or OWL_DEFAULT_PROMPTS) if p and p.strip()]
        if not self.prompts:
            raise ValueError("OwlDetector needs at least one prompt")
        self.labels = [_strip_article(p) for p in self.prompts]
        self.threshold = float(threshold)
        self.nms_iou = float(nms_iou)
        self.max_boxes = int(max_boxes)
        self.ignore = set(s.lower() for s in (ignore or ()))
        eng = os.path.expanduser(engine) if engine else None
        if eng and not os.path.isfile(eng):
            print("OwlDetector: engine {} not found; running the image encoder in PyTorch".format(eng), flush=True)
            eng = None
        self.engine = eng
        self.predictor = OwlPredictor(model, image_encoder_engine=eng)
        self.text_encodings = self.predictor.encode_text(self.prompts)
        self.slim = owl_slim_enabled() if slim is None else bool(slim)
        self.slimmed = []  # type: List[str]
        if self.slim:
            self.slimmed = slim_owl_predictor(self.predictor, self.text_encodings)
        self.timing = _Timing()

    def detect(self, color: np.ndarray) -> List[RawBox]:
        _check_image(color)
        t0 = time.time()
        height, width = color.shape[:2]
        image = self._Image.fromarray(np.ascontiguousarray(color[:, :, :3], dtype=np.uint8))
        out = self.predictor.predict(image=image, text=self.prompts,
                                     text_encodings=self.text_encodings, threshold=self.threshold)
        boxes = []  # type: List[RawBox]
        xyxy = _to_numpy(out.boxes).reshape(-1, 4)
        scores = _to_numpy(out.scores).reshape(-1)
        labels = _to_numpy(out.labels).reshape(-1)
        for (l, t, r, b), s, k in zip(xyxy, scores, labels):
            box = clip_box(l, t, r, b, width, height)
            if box is None:
                continue
            label = self.labels[int(k)] if 0 <= int(k) < len(self.labels) else str(int(k))
            if label.lower() in self.ignore:
                continue
            boxes.append(RawBox(box=box, label=label, conf=float(s)))
        boxes = nms_boxes(boxes, self.nms_iou, self.max_boxes)
        self.timing.add(time.time() - t0)
        return boxes

    def fps(self) -> float:
        return self.timing.fps()


_TRUE = ("1", "true", "yes", "on")


def owl_slim_enabled() -> bool:
    """OFB_OWL_SLIM=1 turns on `slim_owl_predictor` (off by default)."""
    import os
    return os.environ.get("OFB_OWL_SLIM", "0").strip().lower() in _TRUE


def _cuda_mb(torch: Any) -> Optional[float]:
    try:
        if torch is not None and torch.cuda.is_available():
            return torch.cuda.memory_allocated() / 1048576.0
    except Exception:
        pass
    return None


def slim_owl_predictor(predictor: Any, text_encodings: Any = None) -> List[str]:
    """Free the parts of a nanoowl OwlPredictor that `predict()` no longer needs.

    nanoowl loads the whole OWL-ViT model onto the GPU. After the prompts are
    encoded once (OwlDetector.__init__), `predict(text_encodings=...)` never calls
    the text encoder again, so `owlvit.text_model` and `owlvit.text_projection` can
    go. With a TensorRT image encoder, `encode_image` calls only the engine, whose
    outputs already include post_layernorm, layer_norm, class_head and box_head
    (nanoowl owl_predictor.py, encode_image_trt / load_image_encoder_engine), so the
    PyTorch `owlvit.vision_model` can go too. Without an engine it is kept, since
    encode_image_torch uses it. The small heads are kept either way.

    `text_encodings.text_embeds` is detached so its autograd graph does not keep the
    text encoder alive. Returns the names that were dropped (empty when the
    predictor does not look like nanoowl's).
    """
    import gc
    try:
        import torch  # type: ignore
    except ImportError:
        torch = None
    owlvit = getattr(getattr(predictor, "model", None), "owlvit", None)
    if owlvit is None:
        return []
    embeds = getattr(text_encodings, "text_embeds", None)
    if embeds is not None and hasattr(embeds, "detach"):
        text_encodings.text_embeds = embeds.detach()
    names = ["text_model", "text_projection"]
    if getattr(predictor, "image_encoder_engine", None) is not None:
        names.append("vision_model")
    before = _cuda_mb(torch)
    dropped = []  # type: List[str]
    for name in names:
        if getattr(owlvit, name, None) is not None:
            setattr(owlvit, name, None)
            dropped.append(name)
    gc.collect()
    if torch is not None:
        try:
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            pass
    after = _cuda_mb(torch)
    msg = "OwlDetector slim: dropped {}".format(", ".join(dropped) or "nothing")
    if before is not None and after is not None:
        msg += " (torch allocated {:.0f} -> {:.0f} MB)".format(before, after)
    print(msg, flush=True)
    return dropped


def _strip_article(prompt: str) -> str:
    p = prompt.strip()
    for art in ("a ", "an ", "the "):
        if p.lower().startswith(art):
            return p[len(art):].strip()
    return p


# ---------------------------------------------------------------- factory
def make_detector(name: str, **kw: Any):
    """Build a detector by name: "detectnet", "yolo", "owl" (NanoOWL), or "fake".

    Keyword arguments go to the detector class; unknown ones are ignored by the
    real detectors so one argument set can be passed to either.
    """
    key = (name or "").strip().lower()
    if key in ("detectnet", "detect_net", "ssd"):
        return DetectNetDetector(**kw)
    if key in ("yolo", "ultralytics"):
        return YoloDetector(**kw)
    if key in ("owl", "nanoowl"):
        return OwlDetector(**kw)
    if key == "fake":
        from objmem.fakes import FakeDetector
        boxes = kw.get("boxes")
        return FakeDetector(boxes) if boxes is not None else FakeDetector()
    raise ValueError("unknown detector {!r}; choose one of {}".format(name, ", ".join(DETECTOR_NAMES)))
