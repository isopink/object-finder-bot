"""scripts/vision_worker.py passes the camera and detector flags through."""
import importlib.util
import os

from objmem.types import Params

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load_script():
    spec = importlib.util.spec_from_file_location("vision_worker_script",
                                                  os.path.join(ROOT, "scripts", "vision_worker.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_real_parts_get_device_engine_threshold(monkeypatch):
    import objmem.camera
    import objmem.detectors
    import objmem.embed

    calls = {}

    class StubClip:
        device, fp16 = "cpu", False

        def __init__(self, **kw):
            calls["clip"] = kw

    def stub_detector(name, **kw):
        calls["detector"] = (name, kw)
        return object()

    def stub_camera(kind, **kw):
        calls["camera"] = (kind, kw)
        return object()

    monkeypatch.setattr(objmem.embed, "ClipEmbedder", StubClip)
    monkeypatch.setattr(objmem.detectors, "make_detector", stub_detector)
    monkeypatch.setattr(objmem.camera, "make_camera", stub_camera)

    mod = _load_script()
    args = mod.build_parser().parse_args(["--detector", "yolo", "--yolo-engine", "y.engine", "--threshold", "0.3",
                                          "--camera", "c920", "--camera-device", "/dev/video2"])
    params = Params()
    mod.build_parts(args, params)
    assert calls["detector"] == ("yolo", {"threshold": 0.3, "model": "yolov8n.pt", "engine": "y.engine"})
    assert calls["camera"][0] == "c920"
    assert calls["camera"][1]["device"] == "/dev/video2"
    assert calls["camera"][1]["width"] == params.img_w

    args = mod.build_parser().parse_args([])
    params.camera_mode = "depth"
    mod.build_parts(args, params)
    assert calls["detector"] == ("detectnet", {})
    assert calls["camera"][0] == "realsense"
    assert "device" not in calls["camera"][1]
