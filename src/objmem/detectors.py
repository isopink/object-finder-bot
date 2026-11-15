"""Object detector adapters behind the `Detector` interface.

    make_detector("detectnet", network="ssd-mobilenet-v2", threshold=0.5)
    make_detector("yolo", model="yolov8n.pt", engine=None, conf=0.4)
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

DETECTOR_NAMES = ("detectnet", "yolo", "fake")


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


# ---------------------------------------------------------------- factory
def make_detector(name: str, **kw: Any):
    """Build a detector by name: "detectnet", "yolo", or "fake".

    Keyword arguments go to the detector class; unknown ones are ignored by the
    real detectors so one argument set can be passed to either.
    """
    key = (name or "").strip().lower()
    if key in ("detectnet", "detect_net", "ssd"):
        return DetectNetDetector(**kw)
    if key in ("yolo", "ultralytics"):
        return YoloDetector(**kw)
    if key == "fake":
        from objmem.fakes import FakeDetector
        boxes = kw.get("boxes")
        return FakeDetector(boxes) if boxes is not None else FakeDetector()
    raise ValueError("unknown detector {!r}; choose one of {}".format(name, ", ".join(DETECTOR_NAMES)))
