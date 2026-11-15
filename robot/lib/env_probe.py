#!/usr/bin/env python
"""Check the Python packages the vision worker needs, inside the conda env.

Usage: python robot/lib/env_probe.py depth|nodepth [detectnet|yolo|fake]

Prints [OK]/[FAIL] per package; exit status 1 if a required one is missing.
Python 3.8 syntax.
"""
import sys

N_FAIL = 0


def ok(msg):
    print("  [OK]   " + msg)


def fail(msg, hint=""):
    global N_FAIL
    N_FAIL += 1
    print("  [FAIL] " + msg)
    if hint:
        print("         hint: " + hint)


def try_import(name, hint, required=True):
    try:
        mod = __import__(name)
        ok("import %s %s" % (name, getattr(mod, "__version__", "")))
        return mod
    except Exception as e:  # noqa: BLE001
        if required:
            fail("import %s: %s" % (name, e), hint)
        else:
            print("  [..]   import %s: %s" % (name, e))
        return None


def main(argv):
    mode = argv[1] if len(argv) > 1 else "depth"
    det = argv[2] if len(argv) > 2 else "detectnet"
    print("  python %s" % sys.version.split()[0])
    try_import("numpy", "conda install numpy")
    try_import("yaml", "pip install pyyaml")
    try_import("objmem", "PYTHONPATH must include <repo>/src (robot/env.sh sets it)")
    torch = try_import("torch", "use the conda env with the JetPack PyTorch wheel; do not pip install torch")
    if torch is not None:
        if torch.cuda.is_available():
            ok("CUDA available: %s" % torch.cuda.get_device_name(0))
        else:
            fail("torch.cuda.is_available() is False", "wrong torch wheel (CPU build) or wrong conda env")
    try_import("open_clip", "pip install open_clip_torch --no-deps (keep the installed torch)")
    try_import("PIL", "pip install pillow")
    if mode == "depth":
        try_import("pyrealsense2", "install librealsense with Python bindings for JetPack (vision/README.md)")
    else:
        if try_import("jetson_utils", "", required=False) is None:
            try_import("cv2", "jetson_utils (jetson-inference) or OpenCV is needed for the C920")
    if det == "detectnet":
        try_import("jetson_inference", "build jetson-inference in this env, or OFB_DETECTOR=yolo")
    elif det == "yolo":
        try_import("ultralytics", "pip install ultralytics --no-deps, or OFB_DETECTOR=detectnet")
    return 1 if N_FAIL else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
