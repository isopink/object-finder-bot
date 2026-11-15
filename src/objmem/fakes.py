"""Fake detector and camera for PCs and tests (numpy only).

FakeCamera draws a few colored rectangles on a gray background (and, in depth
mode, a depth image with those rectangles closer than the background).
FakeDetector returns the same rectangles as detector boxes by default.
FakeEmbedder (objmem.embed) maps a crop's dominant color to a vector that is
close to the text embedding of a sentence naming that color, so
"a red mug" is found in a FakeCamera frame and "a green plant" is not.
"""
import time
from collections import namedtuple
from typing import Callable, List, Optional, Sequence, Tuple

import numpy as np

from objmem.embed import FAKE_BACKGROUND_RGB, FAKE_COLORS
from objmem.types import Frame, RawBox

# label, color name (key of FAKE_COLORS), box as fractions (l, t, r, b) of the frame, depth (m)
FakeObject = namedtuple("FakeObject", ["label", "color", "box_frac", "depth_m"])

DEFAULT_OBJECTS = [
    FakeObject("cup", "red", (0.15, 0.40, 0.30, 0.70), 1.2),
    FakeObject("book", "blue", (0.55, 0.45, 0.85, 0.75), 2.0),
]

BACKGROUND_DEPTH_M = 3.5


def _frac_to_box(frac, w, h) -> Tuple[int, int, int, int]:
    l, t, r, b = frac
    return int(round(l * w)), int(round(t * h)), int(round(r * w)), int(round(b * h))


def _clip_box(box, w, h):
    l, t, r, b = [int(v) for v in box]
    l, r = max(0, min(w, l)), max(0, min(w, r))
    t, b = max(0, min(h, t)), max(0, min(h, b))
    return l, t, r, b


class FakeDetector:
    """Implements Detector.

    boxes=None: the DEFAULT_OBJECTS rectangles, scaled to the frame size.
    Otherwise a list of RawBox, (box, label, conf), (box, label) or bare boxes in pixels,
    returned on every call (clipped to the frame). boxes=[] returns nothing.
    """

    def __init__(self, boxes: Optional[Sequence] = None, objects: Optional[Sequence[FakeObject]] = None):
        self.boxes = None if boxes is None else list(boxes)
        self.objects = list(DEFAULT_OBJECTS if objects is None else objects)
        self.calls = 0

    def detect(self, color: np.ndarray) -> List[RawBox]:
        self.calls += 1
        h, w = color.shape[:2]
        out = []
        if self.boxes is None:
            for obj in self.objects:
                out.append(RawBox(_frac_to_box(obj.box_frac, w, h), obj.label, 0.9))
            return out
        for item in self.boxes:
            if isinstance(item, RawBox):
                box, label, conf = item.box, item.label, item.conf
            else:
                item = tuple(item)
                if len(item) == 4 and all(np.isscalar(v) for v in item):
                    box, label, conf = item, "object", 0.9
                else:
                    box = item[0]
                    label = item[1] if len(item) > 1 else "object"
                    conf = float(item[2]) if len(item) > 2 else 0.9
            out.append(RawBox(_clip_box(box, w, h), label, float(conf)))
        return out


class FakeCamera:
    """Implements FrameSource. mode "depth" gives a depth image, "nodepth" gives depth=None.

    size is (width, height). Set `available = False` to make read() return None.
    """

    def __init__(self, mode: str = "depth", size: Tuple[int, int] = (640, 480),
                 objects: Optional[Sequence[FakeObject]] = None,
                 background_depth: float = BACKGROUND_DEPTH_M,
                 clock: Callable[[], float] = time.time):
        if mode not in ("depth", "nodepth"):
            raise ValueError("mode must be 'depth' or 'nodepth', got {!r}".format(mode))
        self.mode = mode
        self.size = (int(size[0]), int(size[1]))
        self.objects = list(DEFAULT_OBJECTS if objects is None else objects)
        self.background_depth = float(background_depth)
        self.clock = clock
        self.available = True
        self.reads = 0

    def render(self) -> Tuple[np.ndarray, Optional[np.ndarray]]:
        w, h = self.size
        color = np.empty((h, w, 3), dtype=np.uint8)
        color[:] = FAKE_BACKGROUND_RGB
        depth = None
        if self.mode == "depth":
            depth = np.full((h, w), self.background_depth, dtype=np.float32)
        for obj in self.objects:
            l, t, r, b = _frac_to_box(obj.box_frac, w, h)
            color[t:b, l:r] = FAKE_COLORS[obj.color]
            if depth is not None:
                depth[t:b, l:r] = obj.depth_m
        return color, depth

    def read(self) -> Optional[Frame]:
        if not self.available:
            return None
        self.reads += 1
        color, depth = self.render()
        return Frame(color=color, depth=depth, t=float(self.clock()))
