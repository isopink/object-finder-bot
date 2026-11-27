"""Camera adapters behind the `FrameSource` interface.

    make_camera("realsense", width=640, height=480, fps=30)   # color + aligned depth (m)
    make_camera("c920", device="/dev/video0", width=1280, height=720)  # color only
    make_camera("fake")                                        # objmem.fakes.FakeCamera
    make_camera("none")                                        # None (no camera)

`read()` returns a `Frame` with `color` (H, W, 3) uint8 RGB, `depth` (H, W)
float32 meters aligned to color (0 = invalid) or None, and `t` (unix seconds),
or None when no frame arrived in time. Hardware libraries (pyrealsense2,
jetson_utils, cv2) are imported only when a camera is built.

`camera_mode` "depth" uses "realsense", "nodepth" uses "c920"
(see `camera_for_mode`).
"""
import math
import re
import time
from typing import Any, Dict, Optional, Tuple, Union

import numpy as np

from objmem.types import Frame

CAMERA_NAMES = ("realsense", "c920", "fake", "none")


def camera_for_mode(camera_mode: str) -> str:
    """Params.camera_mode -> camera kind."""
    mode = (camera_mode or "").strip().lower()
    if mode == "depth":
        return "realsense"
    if mode == "nodepth":
        return "c920"
    raise ValueError("camera_mode must be 'depth' or 'nodepth', got {!r}".format(camera_mode))


def _size(width: Optional[int], height: Optional[int], size: Optional[Tuple[int, int]],
          default: Tuple[int, int]) -> Tuple[int, int]:
    if size is not None:
        return int(size[0]), int(size[1])
    return int(width or default[0]), int(height or default[1])


def to_rgb(image: np.ndarray, order: str = "rgb") -> np.ndarray:
    """Any camera image -> contiguous (H, W, 3) uint8 RGB.

    Accepts gray (H, W), RGB, RGBA, BGR, or BGRA (`order` "rgb" or "bgr").
    Float images in [0, 255] (jetson_utils rgb32f) are converted to uint8.
    """
    arr = np.asarray(image)
    if arr.ndim == 2:
        arr = np.stack([arr] * 3, axis=-1)
    if arr.ndim != 3 or arr.shape[2] < 3:
        raise ValueError("unexpected image shape {}".format(arr.shape))
    arr = arr[:, :, :3]
    if order == "bgr":
        arr = arr[:, :, ::-1]
    if arr.dtype != np.uint8:
        arr = np.clip(arr, 0, 255).astype(np.uint8)
    return np.ascontiguousarray(arr)


def intrinsics_to_params(fx: float, fy: float, ppx: float, ppy: float,
                         width: int, height: int) -> Dict[str, float]:
    """Pinhole intrinsics -> the camera keys of config/default.yaml."""
    return {
        "img_w": int(width),
        "img_h": int(height),
        "fx": float(fx),
        "fy": float(fy),
        "cx": float(ppx),
        "cy": float(ppy),
        "hfov": 2.0 * math.atan(float(width) / (2.0 * float(fx))),
    }


# ---------------------------------------------------------------- RealSense
class RealSenseCamera(object):
    """Intel RealSense: color (rgb8) and depth (z16) aligned to the color image.

    Depth is converted to float32 meters with the device depth scale; 0 = no depth.
    `intrinsics()` gives the color intrinsics as config keys.

    When the stream has stopped (`restart_after` reads in a row without a frame) read()
    restarts the pipeline, and every third restart resets the device first. On 2026-11-27
    a D455F delivered no frame at all after the worker had started (every request answered
    "no frame from the camera"), and restarting the whole worker to get the camera back is
    not possible on the Jetson (its GPU memory does not come back without a reboot).
    """

    def __init__(self, width: Optional[int] = None, height: Optional[int] = None, fps: int = 30,
                 serial: Optional[str] = None, timeout_ms: int = 1000,
                 size: Optional[Tuple[int, int]] = None, first_timeout_ms: int = 10000,
                 restart_after: int = 2, restart_gap_s: float = 5.0, reset_wait_s: float = 5.0,
                 **_unused: Any) -> None:
        import pyrealsense2 as rs
        self._rs = rs
        self.width, self.height = _size(width, height, size, (640, 480))
        self.fps = int(fps)
        self.timeout_ms = int(timeout_ms)
        # The first color frame can take ~3 s after the stream starts (auto
        # exposure; seen on a D455F, 2026-11-20). Until one frame has arrived,
        # read() waits up to first_timeout_ms instead of timeout_ms.
        self.first_timeout_ms = max(int(first_timeout_ms), self.timeout_ms)
        self._got_frame = False
        self.pipeline = rs.pipeline()
        config = rs.config()
        if serial:
            config.enable_device(str(serial))
        config.enable_stream(rs.stream.color, self.width, self.height, rs.format.rgb8, self.fps)
        config.enable_stream(rs.stream.depth, self.width, self.height, rs.format.z16, self.fps)
        self._config = config
        self.restart_after = max(1, int(restart_after))
        self.restart_gap_s = float(restart_gap_s)
        self.reset_wait_s = float(reset_wait_s)
        self._fails = 0             # reads without a frame since the last frame or restart
        self._restarts = 0          # restarts since the last frame
        self._last_restart = 0.0
        self.total_restarts = 0
        self.profile = self.pipeline.start(config)
        self.depth_scale = float(self.profile.get_device().first_depth_sensor().get_depth_scale())
        self.align = rs.align(rs.stream.color)
        self._color_order = "rgb"

    def read(self) -> Optional[Frame]:
        timeout = self.timeout_ms if self._got_frame else self.first_timeout_ms
        try:
            frames = self.pipeline.wait_for_frames(timeout)
        except RuntimeError:
            return self._no_frame()  # "Frame didn't arrive within ..." timeout
        if not frames:
            return self._no_frame()
        self._got_frame = True
        aligned = self.align.process(frames)
        color_frame = aligned.get_color_frame()
        depth_frame = aligned.get_depth_frame()
        if not color_frame or not depth_frame:
            return self._no_frame()
        self._fails = 0
        self._restarts = 0
        color = to_rgb(np.asanyarray(color_frame.get_data()), self._color_order)
        raw = np.asanyarray(depth_frame.get_data())
        depth = raw.astype(np.float32) * np.float32(self.depth_scale)
        return Frame(color=color, depth=depth, t=time.time())

    def _no_frame(self) -> None:
        """Count a read without a frame; restart the stream when it has stopped. Returns None."""
        self._fails += 1
        now = time.time()
        if self._fails < self.restart_after or now - self._last_restart < self.restart_gap_s:
            return None
        self._last_restart = now
        self._fails = 0
        self._restarts += 1
        self.total_restarts += 1
        hard = self._restarts % 3 == 0
        print("[WARN] RealSense: no frames; restarting the stream{} (restart {})".format(
            " after a device reset" if hard else "", self.total_restarts), flush=True)
        try:
            try:
                self.pipeline.stop()
            except Exception:  # noqa: BLE001 - a dead pipeline may refuse to stop
                pass
            if hard:
                reset = getattr(self.profile.get_device(), "hardware_reset", None)
                if reset is not None:
                    reset()
                    time.sleep(self.reset_wait_s)   # the device leaves the bus and comes back
            self.pipeline = self._rs.pipeline()
            self.profile = self.pipeline.start(self._config)
            self._got_frame = False                 # wait first_timeout_ms for the next frame
        except Exception as exc:  # noqa: BLE001 - keep serving; the next reads try again
            print("[WARN] RealSense: restart failed: {}: {}".format(type(exc).__name__, exc), flush=True)
        return None

    def intrinsics(self) -> Dict[str, float]:
        """Color intrinsics as config keys (img_w, img_h, fx, fy, cx, cy, hfov)."""
        stream = self.profile.get_stream(self._rs.stream.color).as_video_stream_profile()
        intr = stream.get_intrinsics()
        return intrinsics_to_params(intr.fx, intr.fy, intr.ppx, intr.ppy, intr.width, intr.height)

    def close(self) -> None:
        try:
            self.pipeline.stop()
        except Exception:
            pass


# ---------------------------------------------------------------- C920 (USB webcam)
def _device_index(device: Union[str, int]) -> Union[int, str]:
    """"/dev/video2", "v4l2:///dev/video2", "2", or 2 -> 2. Other strings stay as they are."""
    if isinstance(device, int):
        return device
    text = str(device)
    m = re.match(r"^(?:v4l2://)?/dev/video(\d+)$", text)
    if m:
        return int(m.group(1))
    if text.isdigit():
        return int(text)
    return text


def _device_uri(device: Union[str, int]) -> str:
    """Device -> jetson_utils videoSource URI ("v4l2:///dev/video0")."""
    if isinstance(device, int) or str(device).isdigit():
        return "v4l2:///dev/video{}".format(int(device))
    text = str(device)
    if text.startswith("/dev/"):
        return "v4l2://" + text
    return text


class C920Camera(object):
    """Logitech C920 (or any V4L2 webcam), color only.

    backend "jetson" uses jetson_utils.videoSource (MJPEG, hardware decode),
    "opencv" uses cv2.VideoCapture, "auto" tries jetson_utils first and falls
    back to OpenCV when it is missing or fails to open the device.
    """

    def __init__(self, device: Union[str, int] = "/dev/video0", width: Optional[int] = None,
                 height: Optional[int] = None, fps: int = 30, backend: str = "auto",
                 timeout_ms: int = 1000, size: Optional[Tuple[int, int]] = None,
                 **_unused: Any) -> None:
        self.device = device
        self.width, self.height = _size(width, height, size, (1280, 720))
        self.fps = int(fps)
        self.timeout_ms = int(timeout_ms)
        self.backend = None  # type: Optional[str]
        self._src = None  # type: Any
        self._utils = None  # type: Any
        self._cv2 = None  # type: Any
        backend = (backend or "auto").lower()
        if backend not in ("auto", "jetson", "opencv"):
            raise ValueError("backend must be auto, jetson, or opencv")
        errors = []
        if backend in ("auto", "jetson"):
            try:
                self._open_jetson()
            except Exception as exc:  # ImportError or a device error
                if backend == "jetson":
                    raise
                errors.append("jetson_utils: {}".format(exc))
        if self.backend is None:
            try:
                self._open_opencv()
            except Exception as exc:
                errors.append("opencv: {}".format(exc))
                raise RuntimeError("cannot open camera {}: {}".format(device, "; ".join(errors)))

    def _open_jetson(self) -> None:
        import jetson_utils
        options = {"width": self.width, "height": self.height, "framerate": self.fps,
                   "codec": "mjpeg", "encoder": "v4l2"}
        self._src = jetson_utils.videoSource(_device_uri(self.device), options=options)
        self._utils = jetson_utils
        self.backend = "jetson"

    def _open_opencv(self) -> None:
        import cv2
        index = _device_index(self.device)
        cap = cv2.VideoCapture(index, cv2.CAP_V4L2) if isinstance(index, int) else cv2.VideoCapture(index)
        if not cap.isOpened():
            raise RuntimeError("cv2.VideoCapture({!r}) did not open".format(index))
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
        cap.set(cv2.CAP_PROP_FPS, self.fps)
        self._src = cap
        self._cv2 = cv2
        self.backend = "opencv"

    def read_cuda(self) -> Any:
        """jetson backend only: the next frame as a cudaImage, or None."""
        if self.backend != "jetson":
            raise RuntimeError("read_cuda needs the jetson backend")
        try:
            return self._src.Capture(timeout=self.timeout_ms)
        except Exception:
            return None  # older jetson_utils raise on timeout

    def read(self) -> Optional[Frame]:
        if self.backend == "jetson":
            img = self.read_cuda()
            if img is None:
                return None
            self._utils.cudaDeviceSynchronize()
            color = to_rgb(self._utils.cudaToNumpy(img), "rgb")
        else:
            ok, bgr = self._src.read()
            if not ok or bgr is None:
                return None
            color = to_rgb(bgr, "bgr")
        return Frame(color=color, depth=None, t=time.time())

    def close(self) -> None:
        try:
            if self.backend == "jetson":
                self._src.Close()
            elif self.backend == "opencv":
                self._src.release()
        except Exception:
            pass


# ---------------------------------------------------------------- factory
def make_camera(kind: str, **kw: Any):
    """Build a camera by kind: "realsense", "c920", "fake", or "none" (returns None).

    Keyword arguments go to the camera class. `width`/`height` or `size=(w, h)`
    work for every kind; real cameras ignore keywords they do not use.
    """
    key = (kind or "").strip().lower()
    if key in ("realsense", "rs", "depth"):
        return RealSenseCamera(**kw)
    if key in ("c920", "webcam", "usb", "nodepth"):
        return C920Camera(**kw)
    if key == "fake":
        from objmem.fakes import FakeCamera
        fake_kw = {}  # type: Dict[str, Any]
        if "mode" in kw:
            fake_kw["mode"] = kw["mode"]
        if kw.get("size") is not None:
            fake_kw["size"] = tuple(kw["size"])
        elif kw.get("width") and kw.get("height"):
            fake_kw["size"] = (int(kw["width"]), int(kw["height"]))
        return FakeCamera(**fake_kw)
    if key in ("none", ""):
        return None
    raise ValueError("unknown camera {!r}; choose one of {}".format(kind, ", ".join(CAMERA_NAMES)))
