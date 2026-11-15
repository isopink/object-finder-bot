"""Crop a frame into pieces for CLIP.

Ported from the old vision/jetson_find_object.py. Every function returns a list
of `Crop(image, box, label)` (a namedtuple, so `crop, box, label = c` works),
where `image` is a copy of the RGB pixels and `box` is (left, top, right, bottom).
"""
from collections import namedtuple
from typing import Iterable, List, Sequence

import numpy as np

Crop = namedtuple("Crop", ["image", "box", "label"])

MIN_CROP_PX = 10  # a crop must be wider and taller than this


def _box_label(det):
    """Accept a RawBox / Detection (has .box, .label) or a tuple (box, label[, conf]) or a bare box."""
    if hasattr(det, "box"):
        return tuple(det.box), getattr(det, "label", "object")
    det = tuple(det)
    if len(det) == 4 and all(np.isscalar(v) for v in det):
        return det, "object"
    return tuple(det[0]), det[1] if len(det) > 1 else "object"


def detection_crops(frame: np.ndarray, detections: Iterable, pad: float = 0.1) -> List[Crop]:
    """Crop along detector boxes, each padded by `pad` of its size, clipped to the frame.

    Crops not larger than MIN_CROP_PX in both directions are skipped.
    """
    h, w = frame.shape[:2]
    out = []
    for det in detections:
        (l0, t0, r0, b0), label = _box_label(det)
        pw, ph = (r0 - l0) * pad, (b0 - t0) * pad
        l, t = int(max(0, l0 - pw)), int(max(0, t0 - ph))
        r, b = int(min(w, r0 + pw)), int(min(h, b0 + ph))
        if r - l > MIN_CROP_PX and b - t > MIN_CROP_PX:
            out.append(Crop(frame[t:b, l:r].copy(), (l, t, r, b), label))
    return out


def grid_crops(frame: np.ndarray, n: int = 3) -> List[Crop]:
    """Split the frame into n x n tiles labeled tile<row><col>."""
    h, w = frame.shape[:2]
    out = []
    for r in range(n):
        for c in range(n):
            l, t, rr, b = c * w // n, r * h // n, (c + 1) * w // n, (r + 1) * h // n
            out.append(Crop(frame[t:b, l:rr].copy(), (l, t, rr, b), "tile{}{}".format(r, c)))
    return out


def sliding_crops(frame: np.ndarray, sizes: Sequence[int] = (2, 3, 4)) -> List[Crop]:
    """Windows of 1/n of the frame for each n in `sizes`, with 50% overlap, labeled win<n>.

    sizes=(2, 3, 4) on a 16:9 frame: 9 + 25 + 49 = 83 windows.
    """
    h, w = frame.shape[:2]
    out = []
    for n in sizes:
        cw, ch = w // n, h // n
        sx, sy = max(1, cw // 2), max(1, ch // 2)  # half-window stride -> 50% overlap
        if cw < 1 or ch < 1:
            continue
        for t in range(0, h - ch + 1, sy):
            for l in range(0, w - cw + 1, sx):
                out.append(Crop(frame[t:t + ch, l:l + cw].copy(), (l, t, l + cw, t + ch), "win{}".format(n)))
    return out
