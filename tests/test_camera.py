"""Camera adapters with pyrealsense2, jetson_utils, and cv2 mocked."""
import math
import sys
import types

import numpy as np
import pytest

from objmem import camera
from objmem.camera import (C920Camera, RealSenseCamera, _device_index, _device_uri,
                           camera_for_mode, intrinsics_to_params, make_camera, to_rgb)
from objmem.types import Frame


# ---------------------------------------------------------------- pyrealsense2 fake
def install_realsense(monkeypatch, frames, depth_scale=0.001):
    """frames: list of (color, depth) arrays, or "timeout" / "missing" entries."""
    rs = types.ModuleType("pyrealsense2")
    state = {"enabled": [], "stopped": False, "device": None, "starts": 0, "stops": 0, "resets": 0}

    class stream(object):
        color, depth = "color", "depth"

    class format(object):
        rgb8, z16 = "rgb8", "z16"

    class Data(object):
        def __init__(self, arr):
            self.arr = arr

        def get_data(self):
            return self.arr

    class FS(object):
        def __init__(self, color, depth):
            self.color, self.depth = color, depth

        def get_color_frame(self):
            return Data(self.color) if self.color is not None else None

        def get_depth_frame(self):
            return Data(self.depth) if self.depth is not None else None

    class config(object):
        def enable_stream(self, s, w, h, f, fps):
            state["enabled"].append((s, w, h, f, fps))

        def enable_device(self, serial):
            state["device"] = serial

    class Intr(object):
        fx, fy, ppx, ppy, width, height = 610.5, 611.0, 321.2, 238.9, 640, 480

    class StreamProfile(object):
        def as_video_stream_profile(self):
            return self

        def get_intrinsics(self):
            return Intr()

    class Profile(object):
        def get_device(self):
            return self

        def first_depth_sensor(self):
            return self

        def get_depth_scale(self):
            return depth_scale

        def hardware_reset(self):
            state["resets"] += 1

        def get_stream(self, s):
            assert s == "color"
            return StreamProfile()

    queue = list(frames)

    class pipeline(object):
        def start(self, cfg):
            state["starts"] += 1
            return Profile()

        def wait_for_frames(self, timeout_ms):
            state.setdefault("timeouts", []).append(timeout_ms)
            item = queue.pop(0)
            if isinstance(item, str) and item == "timeout":
                raise RuntimeError("Frame didn't arrive within {}".format(timeout_ms))
            if isinstance(item, str):
                return FS(None, None)
            return FS(*item)

        def stop(self):
            state["stopped"] = True
            state["stops"] += 1

    class align(object):
        def __init__(self, to):
            state["align_to"] = to

        def process(self, fs):
            return fs

    rs.stream, rs.format, rs.config, rs.pipeline, rs.align = stream, format, config, pipeline, align
    monkeypatch.setitem(sys.modules, "pyrealsense2", rs)
    return state


def test_realsense_depth_in_meters_and_rgb(monkeypatch):
    color = np.zeros((480, 640, 3), np.uint8)
    color[..., 0] = 255
    depth = np.full((480, 640), 1500, np.uint16)
    depth[0, 0] = 0
    state = install_realsense(monkeypatch, [(color, depth), "timeout", "missing"])
    cam = make_camera("realsense", width=640, height=480, fps=15, serial="123")
    assert isinstance(cam, RealSenseCamera)
    assert ("color", 640, 480, "rgb8", 15) in state["enabled"]
    assert ("depth", 640, 480, "z16", 15) in state["enabled"]
    assert state["align_to"] == "color" and state["device"] == "123"
    fr = cam.read()
    assert isinstance(fr, Frame)
    assert fr.color.shape == (480, 640, 3) and fr.color.dtype == np.uint8
    assert fr.color[0, 0, 0] == 255 and fr.color[0, 0, 2] == 0
    assert fr.depth.shape == (480, 640) and fr.depth.dtype == np.float32
    assert fr.depth[1, 1] == pytest.approx(1.5) and fr.depth[0, 0] == 0.0
    assert fr.t > 0
    assert cam.read() is None   # timeout
    assert cam.read() is None   # frameset without color/depth
    cam.close()
    assert state["stopped"]


def test_realsense_restarts_a_stream_that_gives_no_frames(monkeypatch):
    # 2026-11-27: the D455F gave no frame at all after the worker had started.
    fs = (np.zeros((4, 6, 3), np.uint8), np.zeros((4, 6), np.uint16))
    state = install_realsense(monkeypatch, ["timeout", "timeout", fs, fs])
    cam = make_camera("realsense", size=(6, 4), restart_gap_s=0.0)
    assert cam.read() is None and state["starts"] == 1          # one miss: keep waiting
    assert cam.read() is None and state["starts"] == 2          # second miss: stream restarted
    assert state["stops"] == 1 and state["resets"] == 0
    assert cam.read() is not None and cam.read() is not None
    assert state["starts"] == 2 and cam.total_restarts == 1     # frames again: no more restarts
    assert state["timeouts"][2] == cam.first_timeout_ms         # waits long for the first frame after a restart


def test_realsense_resets_the_device_on_the_third_restart(monkeypatch):
    fs = (np.zeros((4, 6, 3), np.uint8), np.zeros((4, 6), np.uint16))
    state = install_realsense(monkeypatch, ["timeout"] * 6 + [fs])
    cam = make_camera("realsense", size=(6, 4), restart_gap_s=0.0, reset_wait_s=0.0)
    for _ in range(6):
        assert cam.read() is None
    assert state["starts"] == 4 and state["resets"] == 1        # restart, restart, reset + restart
    assert cam.read() is not None


def test_realsense_does_not_restart_more_often_than_the_gap(monkeypatch):
    state = install_realsense(monkeypatch, ["timeout"] * 8)
    cam = make_camera("realsense", size=(6, 4), restart_gap_s=3600.0)
    for _ in range(8):
        assert cam.read() is None
    assert state["starts"] == 2                                 # the first restart only


def test_realsense_read_color_skips_depth(monkeypatch):
    color = np.zeros((480, 640, 3), np.uint8)
    color[..., 0] = 200
    state = install_realsense(monkeypatch, [(color, np.full((480, 640), 1500, np.uint16)), "timeout"])
    cam = make_camera("realsense", width=640, height=480)
    fr = cam.read_color()
    assert fr is not None and fr.depth is None and fr.color[0, 0, 0] == 200
    assert cam.read_color() is None                         # a missed frame counts like in read()
    assert cam._fails == 1


def test_realsense_waits_longer_for_the_first_frame(monkeypatch):
    fs = (np.zeros((4, 6, 3), np.uint8), np.zeros((4, 6), np.uint16))
    state = install_realsense(monkeypatch, ["timeout", fs, fs])
    cam = make_camera("realsense", size=(6, 4), timeout_ms=1000)
    assert cam.read() is None       # still waiting for the first frame
    assert cam.read() is not None
    assert cam.read() is not None
    assert state["timeouts"] == [10000, 10000, 1000]


def test_realsense_other_depth_scale(monkeypatch):
    depth = np.full((4, 6), 400, np.uint16)
    install_realsense(monkeypatch, [(np.zeros((4, 6, 3), np.uint8), depth)], depth_scale=0.0025)
    fr = make_camera("realsense", size=(6, 4)).read()
    assert fr.depth[0, 0] == pytest.approx(1.0)


def test_realsense_intrinsics(monkeypatch):
    install_realsense(monkeypatch, [])
    intr = make_camera("realsense").intrinsics()
    assert intr["fx"] == 610.5 and intr["cy"] == 238.9 and intr["img_w"] == 640
    assert intr["hfov"] == pytest.approx(2 * math.atan(640 / (2 * 610.5)))


# ---------------------------------------------------------------- jetson_utils fake
class FakeCuda(object):
    def __init__(self, arr):
        self.arr = arr
        self.height, self.width = arr.shape[:2]


def install_jetson_utils(monkeypatch, captures):
    ju = types.ModuleType("jetson_utils")
    state = {"synced": 0, "closed": False}
    queue = list(captures)

    class videoSource(object):
        def __init__(self, uri, options=None):
            state["uri"], state["options"] = uri, options

        def Capture(self, timeout=1000):
            item = queue.pop(0)
            if isinstance(item, str):
                raise Exception("videoSource timeout")
            return None if item is None else FakeCuda(item)

        def Close(self):
            state["closed"] = True

    def sync():
        state["synced"] += 1

    ju.videoSource = videoSource
    ju.cudaDeviceSynchronize = sync
    ju.cudaToNumpy = lambda img: img.arr
    monkeypatch.setitem(sys.modules, "jetson_utils", ju)
    return state


def test_c920_jetson_backend(monkeypatch):
    rgba = np.zeros((720, 1280, 4), np.uint8)
    rgba[..., 0] = 9
    rgba[..., 3] = 255
    state = install_jetson_utils(monkeypatch, [rgba, None, "raise"])
    cam = make_camera("c920", device="/dev/video2", width=1280, height=720)
    assert isinstance(cam, C920Camera) and cam.backend == "jetson"
    assert state["uri"] == "v4l2:///dev/video2"
    assert state["options"]["width"] == 1280 and state["options"]["codec"] == "mjpeg"
    fr = cam.read()
    assert fr.color.shape == (720, 1280, 3) and fr.color.dtype == np.uint8
    assert fr.color[0, 0, 0] == 9 and fr.depth is None and state["synced"] == 1
    assert cam.read() is None    # timeout returns None
    assert cam.read() is None    # timeout raises in older jetson_utils
    cam.close()
    assert state["closed"]


def test_c920_float_frames_become_uint8(monkeypatch):
    img = np.full((4, 4, 3), 300.0, np.float32)
    install_jetson_utils(monkeypatch, [img])
    fr = make_camera("c920").read()
    assert fr.color.dtype == np.uint8 and fr.color.max() == 255


# ---------------------------------------------------------------- cv2 fake
def install_cv2(monkeypatch, reads, opened=True):
    cv2 = types.ModuleType("cv2")
    state = {"set": {}}
    queue = list(reads)
    cv2.CAP_V4L2, cv2.CAP_PROP_FOURCC = 200, 6
    cv2.CAP_PROP_FRAME_WIDTH, cv2.CAP_PROP_FRAME_HEIGHT, cv2.CAP_PROP_FPS = 3, 4, 5
    cv2.VideoWriter_fourcc = lambda *c: "".join(c)

    class VideoCapture(object):
        def __init__(self, index, api=None):
            state["index"], state["api"] = index, api

        def isOpened(self):
            return opened

        def set(self, k, v):
            state["set"][k] = v

        def read(self):
            item = queue.pop(0)
            return (False, None) if item is None else (True, item)

        def release(self):
            state["released"] = True

    cv2.VideoCapture = VideoCapture
    monkeypatch.setitem(sys.modules, "cv2", cv2)
    return state


def test_c920_opencv_backend_bgr_to_rgb(monkeypatch):
    bgr = np.zeros((480, 640, 3), np.uint8)
    bgr[..., 0] = 50   # blue
    bgr[..., 2] = 220  # red
    state = install_cv2(monkeypatch, [bgr, None])
    cam = make_camera("c920", device="v4l2:///dev/video1", backend="opencv", width=640, height=480)
    assert cam.backend == "opencv" and state["index"] == 1 and state["api"] == 200
    assert state["set"][3] == 640 and state["set"][6] == "MJPG"
    fr = cam.read()
    assert fr.color[0, 0, 0] == 220 and fr.color[0, 0, 2] == 50
    assert fr.color.flags["C_CONTIGUOUS"] and fr.depth is None
    assert cam.read() is None
    cam.close()
    assert state["released"]


def test_c920_auto_falls_back_to_opencv(monkeypatch):
    monkeypatch.setitem(sys.modules, "jetson_utils", None)  # import raises ImportError
    install_cv2(monkeypatch, [np.zeros((2, 2, 3), np.uint8)])
    cam = make_camera("c920")
    assert cam.backend == "opencv"
    assert cam.read().color.shape == (2, 2, 3)


def test_c920_no_backend_raises(monkeypatch):
    monkeypatch.setitem(sys.modules, "jetson_utils", None)
    install_cv2(monkeypatch, [], opened=False)
    with pytest.raises(RuntimeError):
        make_camera("c920")
    monkeypatch.setitem(sys.modules, "jetson_utils", None)
    with pytest.raises(ImportError):
        make_camera("c920", backend="jetson")


# ---------------------------------------------------------------- helpers and factory
def test_helpers():
    assert _device_index("/dev/video3") == 3 and _device_index("v4l2:///dev/video0") == 0
    assert _device_index("1") == 1 and _device_index(2) == 2
    assert _device_index("rtsp://cam/stream") == "rtsp://cam/stream"
    assert _device_uri("/dev/video0") == "v4l2:///dev/video0" and _device_uri(1) == "v4l2:///dev/video1"
    assert camera_for_mode("depth") == "realsense" and camera_for_mode("nodepth") == "c920"
    with pytest.raises(ValueError):
        camera_for_mode("stereo")
    p = intrinsics_to_params(500.0, 500.0, 320.0, 240.0, 640, 480)
    assert p["hfov"] == pytest.approx(2 * math.atan(0.64))
    gray = to_rgb(np.arange(4, dtype=np.uint8).reshape(2, 2))
    assert gray.shape == (2, 2, 3)
    with pytest.raises(ValueError):
        to_rgb(np.zeros((2, 2, 2), np.uint8))


def test_make_camera_none_and_unknown():
    assert make_camera("none") is None
    with pytest.raises(ValueError):
        make_camera("kinect")


def test_import_does_not_need_hardware_modules():
    for name in ("pyrealsense2", "jetson_utils", "cv2"):
        assert name not in camera.__dict__


@pytest.mark.parametrize("mode", ["depth", "nodepth"])
def test_make_camera_fake(mode):
    fakes = pytest.importorskip("objmem.fakes")
    cam = make_camera("fake", mode=mode, size=(320, 240))
    assert isinstance(cam, fakes.FakeCamera)
    fr = cam.read()
    assert fr.color.shape[2] == 3
    assert (fr.depth is None) == (mode == "nodepth")
