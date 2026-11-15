"""The vision/ tools (Session 8): import on a PC, pure helpers, and find_object with fakes."""
import importlib.util
import io
import math
import os
import sys
import types

import numpy as np
import pytest

from objmem.types import Params, RawBox

VISION = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "vision")
SCRIPTS = ["find_object", "bench_clip", "bench_detector", "print_intrinsics"]


def load(name):
    spec = importlib.util.spec_from_file_location("vision_" + name, os.path.join(VISION, name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def needs_vision_core():
    for mod in ("objmem.crops", "objmem.verify", "objmem.embed", "objmem.fakes"):
        pytest.importorskip(mod)


def test_old_files_are_gone():
    assert not os.path.exists(os.path.join(VISION, "jetson_find_object.py"))
    assert not os.path.exists(os.path.join(VISION, "clip_jetson_test.py"))
    for name in SCRIPTS:
        assert os.path.exists(os.path.join(VISION, name + ".py"))
    assert os.path.exists(os.path.join(VISION, "README.md"))


@pytest.mark.parametrize("name", ["bench_clip", "bench_detector", "print_intrinsics"])
def test_scripts_import_without_hardware(name):
    mod = load(name)
    assert callable(mod.main)
    for heavy in ("torch", "open_clip", "jetson_inference", "jetson_utils", "pyrealsense2", "ultralytics"):
        assert heavy not in mod.__dict__


def test_find_object_imports():
    needs_vision_core()
    mod = load("find_object")
    assert callable(mod.main)
    args = mod.parse_args(["--fake"])
    assert args.camera == "fake" and args.detector == "fake" and args.fake_clip


# ---------------------------------------------------------------- print_intrinsics
def test_print_intrinsics_format():
    mod = load("print_intrinsics")
    values = mod.from_hfov(1280, 720, 70.0)
    assert values["hfov"] == pytest.approx(math.radians(70.0))
    assert values["cx"] == 640.0 and values["fx"] == pytest.approx(1280 / (2 * math.tan(math.radians(35))))
    text = mod.format_yaml(values, "note")
    lines = text.splitlines()
    assert lines[0] == "# note"
    keys = [ln.split(":")[0] for ln in lines[1:]]
    assert keys == ["img_w", "img_h", "fx", "fy", "cx", "cy", "hfov"]
    # the printed keys parse as YAML and are valid Params keys
    import yaml
    data = yaml.safe_load(text)
    p = Params()
    for k, v in data.items():
        assert hasattr(p, k)
    assert data["img_w"] == 1280


def test_print_intrinsics_c920_cli(capsys):
    mod = load("print_intrinsics")
    assert mod.main(["--width", "640", "--height", "480", "--c920-hfov-deg", "60"]) == 0
    assert "fx: " in capsys.readouterr().out


def test_print_intrinsics_realsense_mocked(monkeypatch, capsys):
    """Use the RealSense fake of test_camera.py."""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    try:
        from test_camera import install_realsense
    finally:
        sys.path.pop(0)
    depth = np.full((480, 640), 2000, np.uint16)
    install_realsense(monkeypatch, [(np.zeros((480, 640, 3), np.uint8), depth)])
    mod = load("print_intrinsics")
    assert mod.main([]) == 0
    out = capsys.readouterr().out
    assert "fx: 610.50" in out and "cy: 238.90" in out and "median 2.00 m" in out


# ---------------------------------------------------------------- bench_detector
class CountingDetector(object):
    def __init__(self):
        self.n = 0

    def detect(self, color):
        self.n += 1
        return [RawBox((0, 0, 10, 10), "cup", 0.8)] if self.n % 2 else []


def test_bench_detector_helpers():
    mod = load("bench_detector")
    frames = [np.zeros((48, 64, 3), np.uint8) for _ in range(10)]
    r = mod.bench(CountingDetector(), frames, warmup=0)
    assert r["frames"] == 10 and r["per_frame"] == 0.5 and r["with_any"] == 0.5
    assert r["labels"]["cup"] == 5 and r["conf"] == pytest.approx(0.8)
    r["load_s"], r["mem_mb"] = 1.0, 12.0
    table = mod.format_rows([("detectnet", r)])
    assert table.splitlines()[0].startswith("| detector") and "| detectnet | 10 |" in table


class FakeCam(object):
    def __init__(self, reads):
        self.reads = list(reads)

    def read(self):
        return self.reads.pop(0) if self.reads else None


def test_bench_detector_capture_stops_on_missing_frames():
    mod = load("bench_detector")
    fr = types.SimpleNamespace(color=np.zeros((2, 2, 3), np.uint8))
    assert len(mod.capture_frames(FakeCam([fr, None, fr]), 5, max_misses=3)) == 2


def test_bench_detector_cli_with_fakes(capsys):
    needs_vision_core()
    mod = load("bench_detector")
    assert mod.main(["--camera", "fake", "--detectors", "fake", "--frames", "6"]) == 0
    out = capsys.readouterr().out
    assert "| fake | 6 |" in out and "cup" in out


# ---------------------------------------------------------------- bench_clip
def test_bench_clip_helpers():
    mod = load("bench_clip")
    images, source = mod.load_images(None, 5)
    assert source == "synthetic noise" and images[0].shape == (480, 640, 3)
    batch = mod.make_batch(images, 83)
    assert len(batch) == 83 and all(b.shape[0] == b.shape[1] and b.shape[0] >= 224 for b in batch)
    assert mod.timed(lambda: None, 3, lambda: None) >= 0.0
    row = {"precision": "FP16", "load_s": 3.0, "img_1": 10.0, "img_83": 166.0, "text_ms": 4.0,
           "mem_model_mb": 300.0, "mem_peak_mb": 700.0, "sanity": "ok"}
    table = mod.format_table([row], [1, 83])
    assert "| FP16 | 3.0 | 10.0 | 166.0 | 2.0 | 4.0 | 300 | 700 | ok |" in table


# ---------------------------------------------------------------- find_object with fakes
@pytest.fixture
def app(tmp_path):
    needs_vision_core()
    from objmem.embed import FakeEmbedder
    from objmem.fakes import FakeCamera, FakeDetector
    mod = load("find_object")
    logs = []
    memory = mod.ScreenMemory(str(tmp_path))
    a = mod.FinderApp(FakeEmbedder(), FakeDetector(), memory, Params(), str(tmp_path), log=logs.append)
    a.logs = logs
    a.cam = FakeCamera("depth", size=(1280, 720))
    a.mod = mod
    return a


def test_find_object_remember_and_query(app, tmp_path):
    color = app.cam.read().color
    assert app.command("q a red cup")
    assert app.last_result == [] and "Memory is empty" in app.logs[-1]
    app.command("s")
    boxes = app.step(color)
    assert len(boxes) == 2 and len(app.memory) == 2
    assert os.path.exists(os.path.join(str(tmp_path), "memory.npz"))
    app.command("q a red cup")
    best_sim, best = app.last_result[0]
    assert app.memory.labels[best] == "cup"
    assert app.overlay()[1][0] == app.memory.boxes[best]
    # memories survive a restart
    again = app.mod.ScreenMemory(str(tmp_path))
    assert len(again) == 2 and again.labels == app.memory.labels
    app.command("t")
    app.step(color)
    assert len(app.memory) == 11 and app.memory.labels[-1] == "tile22"
    app.command("l")
    assert any("tile00" in s for s in app.logs)
    app.command("x")
    assert len(app.memory) == 0 and not os.path.exists(os.path.join(str(tmp_path), "memory.npz"))


def test_find_object_frame_search(app):
    color = app.cam.read().color
    app.command("f a red cup")
    app.step(color)
    found, prob, box = app.last_result
    assert found and prob >= 0.5
    l, t, r, b = box
    cx, cy = (l + r) / 2.0, (t + b) / 2.0
    assert 0.15 * 1280 <= cx <= 0.30 * 1280 and 0.40 * 720 <= cy <= 0.70 * 720  # on the red cup
    assert any("windows" in s for s in app.logs)
    app.command("f a green plant")
    app.step(color)
    assert app.last_result[0] is False and app.overlay()[1][0] is None


def test_find_object_other_commands(app):
    assert app.command("") and app.command("h") and app.command("nonsense")
    assert "Unknown command" in app.logs[-1]
    assert app.command("exit") is False


def test_find_object_main_with_fakes(tmp_path, monkeypatch, capsys):
    needs_vision_core()
    mod = load("find_object")
    monkeypatch.setattr(sys, "stdin", io.StringIO("s\nf a red cup\nq a blue book\n"))
    code = mod.main(["--fake", "--output", "none", "--memory-dir", str(tmp_path), "--max-frames", "50"])
    assert code == 0
    out = capsys.readouterr().out
    assert "Added 2 memories" in out and "-> found" in out and "memory search" in out


def test_find_object_video_out_mocked(monkeypatch):
    needs_vision_core()
    mod = load("find_object")
    calls = {"rects": [], "texts": [], "rendered": 0}

    class Img(object):
        def __init__(self, arr):
            self.height, self.width = arr.shape[:2]

    class Font(object):
        White, Gray40 = "white", "gray"

        def OverlayText(self, img, w, h, text, x, y, fg, bg):
            calls["texts"].append(text)

    class Out(object):
        def __init__(self, uri, options=None):
            calls["uri"] = uri

        def Render(self, img):
            calls["rendered"] += 1

        def SetStatus(self, s):
            pass

        def IsStreaming(self):
            return True

    ju = types.ModuleType("jetson_utils")
    ju.videoOutput, ju.cudaFont = Out, Font
    ju.cudaFromNumpy = Img
    ju.cudaDrawRect = lambda img, rect, color: calls["rects"].append(rect)
    monkeypatch.setitem(sys.modules, "jetson_utils", ju)
    video = mod.VideoOut("webrtc://@:8554/mystream")
    ok = video.render(np.zeros((720, 1280, 3), np.uint8), [RawBox((1, 2, 30, 40), "cup", 0.9)],
                      ((5, 6, 50, 60), "NOW: cup (0.90)", 0.0), "memory: 2")
    assert ok and calls["rendered"] == 1 and calls["uri"] == "webrtc://@:8554/mystream"
    assert calls["rects"] == [(1, 2, 30, 40), (5, 6, 50, 60)]
    assert "cup 90%" in calls["texts"] and "memory: 2" in calls["texts"]
    assert mod.VideoOut("none").render(None, [], None, "") is True
