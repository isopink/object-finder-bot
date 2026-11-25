"""Vision worker: camera + detector + CLIP behind an HTTP/JSON server (no ROS).

Run on the Jetson (conda env test1001):
  python scripts/vision_worker.py --config config/default.yaml
  python scripts/vision_worker.py --config config/default.yaml --detector yolo --camera c920
  python scripts/vision_worker.py --config config/default.yaml --detector yolo       --yolo-engine ~/models/yolov8n.engine --threshold 0.4 --camera c920 --camera-device /dev/video2
On a PC, without hardware or CLIP:
  python scripts/vision_worker.py --fake

Check it:  curl http://127.0.0.1:8600/health

--camera defaults from camera_mode in the config (depth -> realsense, nodepth -> c920).
--camera none serves only requests that send an image (image_source:=ros).
"""
import argparse
import inspect
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(os.path.dirname(HERE), "src")
if os.path.isdir(SRC) and SRC not in sys.path:
    sys.path.insert(0, SRC)

from objmem.types import Params  # noqa: E402


def _call_with_supported(fn, *args, **kw):
    """Call fn with only the keyword arguments its signature accepts."""
    try:
        sig = inspect.signature(fn)
    except (TypeError, ValueError):
        return fn(*args, **kw)
    if any(p.kind == p.VAR_KEYWORD for p in sig.parameters.values()):
        return fn(*args, **kw)
    return fn(*args, **{k: v for k, v in kw.items() if k in sig.parameters})


def build_parser():
    ap = argparse.ArgumentParser(description="objmem vision worker (HTTP server)")
    ap.add_argument("--config", default=None, help="YAML with Params keys (config/default.yaml)")
    ap.add_argument("--fake", action="store_true", help="FakeEmbedder, FakeDetector, FakeCamera (runs on a PC)")
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=8600)
    ap.add_argument("--detector", default="detectnet", choices=["detectnet", "yolo", "owl", "fake"])
    ap.add_argument("--camera", default=None, choices=["realsense", "c920", "fake", "none"],
                    help="default: realsense when camera_mode is depth, c920 when nodepth")
    ap.add_argument("--camera-device", default="/dev/video0", help="C920 device (c920 camera only)")
    ap.add_argument("--threshold", type=float, default=None,
                    help="detector confidence threshold (default: 0.5 detectnet, 0.4 yolo, 0.15 owl)")
    ap.add_argument("--yolo-model", default="yolov8n.pt", help="ultralytics weights (yolo detector only)")
    ap.add_argument("--yolo-engine", default=None, help="TensorRT .engine built on the Jetson (yolo detector only)")
    ap.add_argument("--owl-engine", default=None,
                    help="NanoOWL image encoder engine (owl detector; default ~/nanoowl/data/owl_image_encoder_patch32.engine)")
    ap.add_argument("--owl-prompts", default=None,
                    help="comma separated phrases for the owl detector, e.g. 'a banana,a water bottle' (default: built-in list)")
    ap.add_argument("--clip-model", default="ViT-B-32")
    ap.add_argument("--clip-pretrained", default="laion2b_s34b_b79k")
    ap.add_argument("--no-fp16", action="store_true")
    ap.add_argument("--verbose", action="store_true", help="log every request")
    return ap


def build_parts(args, params):
    """(embedder, detector, camera or None)."""
    kind = args.camera
    if kind is None:
        if args.fake:
            kind = "fake"
        else:
            kind = "realsense" if params.camera_mode == "depth" else "c920"
    mode = params.camera_mode

    if args.fake:
        from objmem.embed import FakeEmbedder
        from objmem.fakes import FakeCamera, FakeDetector
        embedder = FakeEmbedder()
        detector = FakeDetector()
        camera = None if kind == "none" else FakeCamera(mode=mode, size=(params.img_w, params.img_h))
        return embedder, detector, camera

    from objmem.embed import ClipEmbedder
    from objmem.detectors import make_detector
    from objmem.camera import make_camera

    print("Loading CLIP {} / {} ... (about 15 s)".format(args.clip_model, args.clip_pretrained), flush=True)
    t0 = time.time()
    embedder = ClipEmbedder(model=args.clip_model, pretrained=args.clip_pretrained, fp16=not args.no_fp16)
    print("CLIP ready on {} (fp16={}) in {:.1f} s".format(embedder.device, embedder.fp16, time.time() - t0), flush=True)
    det_kw = {}
    if args.threshold is not None:
        det_kw["threshold"] = args.threshold
    if args.detector == "yolo":
        det_kw["model"] = args.yolo_model
        if args.yolo_engine:
            det_kw["engine"] = args.yolo_engine
    if args.detector == "owl":
        if args.owl_engine:
            det_kw["engine"] = args.owl_engine
        if args.owl_prompts:
            det_kw["prompts"] = [s for s in args.owl_prompts.split(",") if s.strip()]
    detector = make_detector(args.detector, **det_kw)
    camera = None
    if kind != "none":
        if kind == "fake":
            camera = make_camera("fake", mode=mode, size=(params.img_w, params.img_h))
        else:
            cam_kw = {"width": params.img_w, "height": params.img_h}
            if kind == "c920":
                cam_kw["device"] = args.camera_device
            camera = _call_with_supported(make_camera, kind, **cam_kw)
    return embedder, detector, camera


def main(argv=None):
    args = build_parser().parse_args(argv)
    params = Params.load(args.config)
    embedder, detector, camera = build_parts(args, params)

    # Fail now, not at the first request: a detector whose TensorRT execution context
    # could not be created (GPU out of memory) loads without an error and then answers
    # every /detect_embed with 500 (NanoOWL, 2026-11-25).
    try:
        import numpy as np
        detector.detect(np.zeros((240, 320, 3), np.uint8))
    except Exception as exc:  # noqa: BLE001
        print("[FAIL] the detector does not run: {}: {}".format(type(exc).__name__, exc), flush=True)
        print("       GPU out of memory? Start the worker before bringup/nav (start_all.sh does), "
              "and see robot/lib/drop_cache.py", flush=True)
        sys.exit(1)

    from objmem.worker import serve

    print("Vision worker on http://{}:{}  (camera_mode={}, camera={}, detector={}, fake={})".format(
        args.host, args.port, params.camera_mode, type(camera).__name__ if camera else "none",
        type(detector).__name__, args.fake), flush=True)
    serve(embedder, detector, camera, params, host=args.host, port=args.port, quiet=not args.verbose)


if __name__ == "__main__":
    main()
