"""Re-check the live view for a query (port of `live_scores` in the old
vision/jetson_find_object.py).

Each window gets a CLIP zero-shot softmax over [query] + background prompts
(prompts contained in the query are dropped) with logit scale
`params.clip_logit_scale` (100). The best window probability >= `params.found_thresh`
counts as found.
"""
from typing import List, Optional, Sequence, Tuple

import numpy as np

from objmem.crops import detection_crops, sliding_crops

DEFAULT_SIZES = (2, 3, 4)


def prompt_list(query: str, background_prompts: Sequence[str]) -> List[str]:
    """[query] followed by the background prompts that are not contained in the query."""
    q = query.lower()
    return [query] + [p for p in background_prompts if p.lower() not in q]


def softmax_probs(image_vecs: np.ndarray, text_vecs: np.ndarray, scale: float = 100.0) -> np.ndarray:
    """(N, D) windows x (K, D) prompts -> (N, K) softmax over prompts of scale * cosine."""
    image_vecs = np.asarray(image_vecs, dtype=np.float64)
    text_vecs = np.asarray(text_vecs, dtype=np.float64)
    logits = scale * image_vecs @ text_vecs.T
    logits -= logits.max(axis=1, keepdims=True)
    probs = np.exp(logits)
    probs /= probs.sum(axis=1, keepdims=True)
    return probs


def live_scores(image_vecs: np.ndarray, query: str, embedder, params) -> Tuple[np.ndarray, np.ndarray]:
    """Probability that each window shows the query rather than a background prompt.

    Returns (probabilities (N,), raw cosine similarity to the query (N,)).
    """
    image_vecs = np.asarray(image_vecs, dtype=np.float32)
    if len(image_vecs) == 0:
        return np.zeros(0), np.zeros(0)
    texts = prompt_list(query, params.background_prompts)
    tvecs = np.stack([np.asarray(embedder.embed_text(t), dtype=np.float32) for t in texts])
    probs = softmax_probs(image_vecs, tvecs, float(params.clip_logit_scale))
    return probs[:, 0], (image_vecs @ tvecs[0]).astype(np.float64)


def frame_crops(color: np.ndarray, boxes, params, sizes: Sequence[int] = DEFAULT_SIZES):
    """Detection crops (padded by params.crop_pad) followed by the sliding windows."""
    return detection_crops(color, boxes or [], pad=float(params.crop_pad)) + sliding_crops(color, sizes)


def score_frame(color: np.ndarray, boxes, query: str, embedder, params, sizes: Sequence[int] = DEFAULT_SIZES):
    """Crops, their probabilities and similarities. For tools that want every window."""
    crops = frame_crops(color, boxes, params, sizes)
    if not crops:
        return crops, np.zeros(0), np.zeros(0)
    vecs = embedder.embed_images([c.image for c in crops])
    probs, sims = live_scores(vecs, query, embedder, params)
    return crops, probs, sims


def check_frame(color: np.ndarray, boxes, query: str, embedder, params) -> Tuple[bool, float, Optional[Tuple[int, int, int, int]]]:
    """Re-check one frame. boxes: detector output (RawBox list) or None.

    Returns (found, best probability, box of the best window when found else None).
    """
    crops, probs, _ = score_frame(color, boxes, query, embedder, params)
    if len(probs) == 0:
        return False, 0.0, None
    best = int(np.argmax(probs))
    prob = float(probs[best])
    found = prob >= float(params.found_thresh)
    return found, prob, (tuple(int(v) for v in crops[best].box) if found else None)
