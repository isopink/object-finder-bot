import numpy as np
import pytest

from objmem.fakes import DEFAULT_OBJECTS, FakeCamera, FakeDetector, FakeObject
from objmem.types import RawBox


def test_camera_depth_and_nodepth():
    f = FakeCamera("depth", size=(320, 240), clock=lambda: 5.0).read()
    assert f.color.shape == (240, 320, 3) and f.color.dtype == np.uint8
    assert f.depth.shape == (240, 320) and f.depth.dtype == np.float32
    assert f.t == 5.0
    l, t, r, b = [int(round(v * s)) for v, s in zip(DEFAULT_OBJECTS[0].box_frac, (320, 240, 320, 240))]
    assert np.allclose(f.depth[(t + b) // 2, (l + r) // 2], DEFAULT_OBJECTS[0].depth_m)
    assert tuple(f.color[(t + b) // 2, (l + r) // 2]) == (220, 30, 30)
    g = FakeCamera("nodepth").read()
    assert g.depth is None


def test_camera_unavailable_and_bad_mode():
    cam = FakeCamera()
    cam.available = False
    assert cam.read() is None
    with pytest.raises(ValueError):
        FakeCamera("stereo")


def test_detector_default_matches_camera_objects():
    cam = FakeCamera(objects=[FakeObject("mug", "green", (0.5, 0.5, 0.75, 1.0), 1.0)], size=(400, 200))
    boxes = FakeDetector(objects=cam.objects).detect(cam.read().color)
    assert boxes == [RawBox((200, 100, 300, 200), "mug", 0.9)]


def test_detector_given_boxes_clipped():
    det = FakeDetector(boxes=[RawBox((-5, 0, 50, 50), "a", 0.7), ((10, 10, 700, 20), "b"), (1, 2, 3, 4)])
    out = det.detect(np.zeros((480, 640, 3), np.uint8))
    assert out[0] == RawBox((0, 0, 50, 50), "a", 0.7)
    assert out[1] == RawBox((10, 10, 640, 20), "b", 0.9)
    assert out[2].label == "object"
    assert FakeDetector(boxes=[]).detect(np.zeros((4, 4, 3), np.uint8)) == []
