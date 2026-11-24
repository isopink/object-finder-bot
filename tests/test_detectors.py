"""Detector adapters with jetson_inference, jetson_utils, and ultralytics mocked."""
import sys
import types

import numpy as np
import pytest

from objmem import detectors
from objmem.detectors import DetectNetDetector, YoloDetector, clip_box, make_detector
from objmem.types import RawBox

CLASSES = {1: "person", 47: "cup", 62: "chair"}


# ---------------------------------------------------------------- fakes
class FakeDet(object):
    def __init__(self, l, t, r, b, cls, conf):
        self.Left, self.Top, self.Right, self.Bottom = l, t, r, b
        self.ClassID, self.Confidence = cls, conf


class FakeCudaImage(object):
    def __init__(self, arr):
        self.arr = arr
        self.height, self.width = arr.shape[:2]


def install_jetson(monkeypatch, detections):
    calls = {}

    class FakeDetectNet(object):
        def __init__(self, network, argv=None, threshold=0.5):
            calls["network"] = network
            calls["threshold"] = threshold

        def Detect(self, img, overlay="box,labels,conf"):
            calls["img"] = img
            calls["overlay"] = overlay
            return list(detections)

        def GetClassDesc(self, cls):
            return CLASSES[cls]

        def GetNetworkFPS(self):
            return 31.0

    ji = types.ModuleType("jetson_inference")
    ji.detectNet = FakeDetectNet
    ju = types.ModuleType("jetson_utils")
    ju.cudaFromNumpy = lambda arr: FakeCudaImage(arr)
    monkeypatch.setitem(sys.modules, "jetson_inference", ji)
    monkeypatch.setitem(sys.modules, "jetson_utils", ju)
    return calls


class FakeTensor(object):
    """Mimics a CUDA torch tensor: needs .cpu() before .numpy()."""

    def __init__(self, data):
        self.data = np.asarray(data, dtype=np.float32)
        self.on_cpu = False

    def cpu(self):
        t = FakeTensor(self.data)
        t.on_cpu = True
        return t

    def numpy(self):
        assert self.on_cpu, "numpy() on a CUDA tensor"
        return self.data


class FakeBoxes(object):
    def __init__(self, xyxy, conf, cls):
        self.xyxy, self.conf, self.cls = FakeTensor(xyxy), FakeTensor(conf), FakeTensor(cls)
        self._n = len(conf)

    def __len__(self):
        return self._n


class FakeResult(object):
    def __init__(self, boxes, names):
        self.boxes, self.names = boxes, names


def install_yolo(monkeypatch, result):
    calls = {}

    class FakeYOLO(object):
        names = {0: "person", 41: "cup"}

        def __init__(self, weights, task=None):
            calls["weights"], calls["task"] = weights, task

        def predict(self, image, **kw):
            calls["image"], calls["kw"] = image, kw
            return [result] if result is not None else []

    ul = types.ModuleType("ultralytics")
    ul.YOLO = FakeYOLO
    monkeypatch.setitem(sys.modules, "ultralytics", ul)
    return calls


def rgb_image(w=640, h=480):
    img = np.zeros((h, w, 3), np.uint8)
    img[:, :, 0] = 200  # red channel
    img[:, :, 2] = 10   # blue channel
    return img


# ---------------------------------------------------------------- helpers
def test_clip_box_rounds_and_clips():
    assert clip_box(-5.2, 10.4, 700.0, 490.6, 640, 480) == (0, 10, 640, 480)
    assert clip_box(10.6, 20.4, 30.5, 40.5, 640, 480) == (11, 20, 30, 40)
    assert clip_box(100, 100, 100, 200, 640, 480) is None
    assert clip_box(700, 10, 800, 20, 640, 480) is None


def test_import_does_not_need_hardware_modules():
    for name in ("jetson_inference", "jetson_utils", "ultralytics", "torch"):
        assert name not in detectors.__dict__


# ---------------------------------------------------------------- detectNet
def test_detectnet_converts_boxes(monkeypatch):
    dets = [FakeDet(10.4, 20.6, 110.2, 220.9, 47, 0.91),
            FakeDet(-20.0, 400.0, 100.0, 520.0, 62, 0.6),   # clipped to the image
            FakeDet(50.0, 50.0, 50.2, 80.0, 47, 0.7)]       # empty after rounding -> dropped
    calls = install_jetson(monkeypatch, dets)
    det = make_detector("detectnet", threshold=0.4)
    assert isinstance(det, DetectNetDetector)
    assert calls["network"] == "ssd-mobilenet-v2" and calls["threshold"] == 0.4
    img = rgb_image()
    out = det.detect(img)
    assert out == [RawBox(box=(10, 21, 110, 221), label="cup", conf=pytest.approx(0.91)),
                   RawBox(box=(0, 400, 100, 480), label="chair", conf=pytest.approx(0.6))]
    assert all(isinstance(v, int) for b in out for v in b.box)
    assert calls["overlay"] == "none"
    sent = calls["img"].arr
    assert sent.shape == (480, 640, 3) and sent.dtype == np.uint8
    assert sent[0, 0, 0] == 200 and sent[0, 0, 2] == 10  # RGB order kept
    assert det.fps() == 31.0


def test_detectnet_ignore_and_empty(monkeypatch):
    install_jetson(monkeypatch, [FakeDet(0, 0, 50, 50, 1, 0.9), FakeDet(0, 0, 60, 60, 47, 0.8)])
    det = make_detector("detectnet", ignore=["Person"])
    assert [b.label for b in det.detect(rgb_image())] == ["cup"]
    install_jetson(monkeypatch, [])
    assert make_detector("detectnet").detect(rgb_image()) == []


def test_detectnet_rgba_input_and_cuda_path(monkeypatch):
    calls = install_jetson(monkeypatch, [FakeDet(1, 2, 30, 40, 47, 0.5)])
    det = make_detector("detectnet")
    rgba = np.zeros((100, 200, 4), np.uint8)
    det.detect(rgba)
    assert calls["img"].arr.shape == (100, 200, 3)
    cuda = FakeCudaImage(np.zeros((100, 200, 3), np.uint8))
    out = det.detect_cuda(cuda, overlay="box,labels,conf")
    assert out[0].box == (1, 2, 30, 40) and calls["overlay"] == "box,labels,conf"


def test_detector_rejects_bad_image(monkeypatch):
    install_jetson(monkeypatch, [])
    det = make_detector("detectnet")
    with pytest.raises(ValueError):
        det.detect(np.zeros((10, 10), np.uint8))


# ---------------------------------------------------------------- YOLO
def test_yolo_converts_boxes_and_flips_to_bgr(monkeypatch):
    result = FakeResult(FakeBoxes([[10.2, 20.7, 100.0, 200.0], [600.0, -3.0, 700.0, 50.0]],
                                  [0.88, 0.45], [41, 0]), {0: "person", 41: "cup"})
    calls = install_yolo(monkeypatch, result)
    det = make_detector("yolo", model="yolov8s.pt", conf=0.3, imgsz=320)
    assert isinstance(det, YoloDetector)
    out = det.detect(rgb_image())
    assert out == [RawBox(box=(10, 21, 100, 200), label="cup", conf=pytest.approx(0.88)),
                   RawBox(box=(600, 0, 640, 50), label="person", conf=pytest.approx(0.45))]
    assert calls["weights"] == "yolov8s.pt" and calls["task"] is None
    assert calls["kw"]["conf"] == 0.3 and calls["kw"]["imgsz"] == 320 and calls["kw"]["half"] is True
    assert calls["kw"]["verbose"] is False
    img = calls["image"]
    assert img.shape == (480, 640, 3) and img.flags["C_CONTIGUOUS"]
    assert img[0, 0, 0] == 10 and img[0, 0, 2] == 200  # BGR for ultralytics


def test_yolo_engine_and_empty(monkeypatch):
    calls = install_yolo(monkeypatch, FakeResult(FakeBoxes(np.zeros((0, 4)), [], []), {}))
    det = make_detector("yolo", engine="/models/yolov8n.engine", threshold=0.6)
    assert calls["weights"] == "/models/yolov8n.engine" and calls["task"] == "detect"
    assert det.detect(rgb_image()) == []
    assert "half" not in calls["kw"] and calls["kw"]["conf"] == 0.6
    install_yolo(monkeypatch, None)
    assert make_detector("yolo").detect(rgb_image()) == []


def test_yolo_names_from_model_and_ignore(monkeypatch):
    result = FakeResult(FakeBoxes([[0, 0, 10, 10], [5, 5, 20, 20], [1, 1, 9, 9]],
                                  [0.9, 0.8, 0.7], [0, 41, 99]), None)
    install_yolo(monkeypatch, result)
    det = make_detector("yolo", ignore=["person"])
    assert [b.label for b in det.detect(rgb_image())] == ["cup", "99"]


# ---------------------------------------------------------------- factory
def test_make_detector_unknown():
    with pytest.raises(ValueError):
        make_detector("no-such-detector")


def test_make_detector_fake():
    fakes = pytest.importorskip("objmem.fakes")
    det = make_detector("fake")
    assert isinstance(det, fakes.FakeDetector)
    out = det.detect(rgb_image())
    assert isinstance(out, list)


# ---------------------------------------------------------------- NanoOWL
def install_owl(monkeypatch, boxes, scores, labels):
    calls = {}

    class FakeOutput(object):
        pass

    class FakeOwlPredictor(object):
        def __init__(self, model, image_encoder_engine=None):
            calls["model"], calls["engine"] = model, image_encoder_engine

        def encode_text(self, texts):
            calls["texts"] = list(texts)
            return "enc"

        def predict(self, image, text, text_encodings, threshold):
            calls["image"], calls["threshold"], calls["enc"] = image, threshold, text_encodings
            o = FakeOutput()
            o.boxes = np.array(boxes, float).reshape(-1, 4)
            o.scores, o.labels = np.array(scores, float), np.array(labels, int)
            return o

    pkg = types.ModuleType("nanoowl")
    mod = types.ModuleType("nanoowl.owl_predictor")
    mod.OwlPredictor = FakeOwlPredictor
    pkg.owl_predictor = mod
    monkeypatch.setitem(sys.modules, "nanoowl", pkg)
    monkeypatch.setitem(sys.modules, "nanoowl.owl_predictor", mod)
    return calls


def test_owl_labels_clip_nms_and_ignore(monkeypatch):
    pytest.importorskip("PIL")
    calls = install_owl(monkeypatch,
                        [[10, 10, 50, 100], [12, 11, 51, 99], [-5, 0, 30, 30], [100, 100, 200, 200],
                         [300, 300, 300, 310]],
                        [0.38, 0.20, 0.31, 0.25, 0.9],
                        [0, 1, 2, 3, 0])
    det = make_detector("owl", prompts=["a water bottle", "a bottle", "an apple", "a person"],
                        engine=None, threshold=0.12, ignore=["person"])
    out = det.detect(rgb_image())
    assert calls["texts"] == ["a water bottle", "a bottle", "an apple", "a person"]
    assert calls["engine"] is None and calls["threshold"] == 0.12 and calls["enc"] == "enc"
    assert calls["image"].size == (640, 480)
    # "bottle" overlaps "water bottle" (IoU > 0.7) and is dropped, the person is
    # ignored, the zero-width box is dropped, negative coordinates are clipped.
    assert [(b.label, b.box) for b in out] == [("water bottle", (10, 10, 50, 100)), ("apple", (0, 0, 30, 30))]
    assert out[0].conf == pytest.approx(0.38)


def test_owl_missing_engine_falls_back(monkeypatch, tmp_path):
    pytest.importorskip("PIL")
    calls = install_owl(monkeypatch, [], [], [])
    det = make_detector("nanoowl", engine=str(tmp_path / "missing.engine"))
    assert calls["engine"] is None
    assert det.detect(rgb_image()) == []
    assert det.labels[calls["texts"].index("a water bottle")] == "water bottle"


def test_nms_boxes_max():
    bs = [RawBox(box=(0, 0, 10, 10), label="a", conf=0.2), RawBox(box=(20, 20, 30, 30), label="b", conf=0.5),
          RawBox(box=(1, 1, 10, 10), label="c", conf=0.9)]
    assert [b.label for b in detectors.nms_boxes(bs)] == ["c", "b"]
    assert [b.label for b in detectors.nms_boxes(bs, max_boxes=1)] == ["c"]
