"""print_intrinsics.py - print the RealSense color intrinsics as config/default.yaml keys.

The depth image is aligned to the color image, so the color intrinsics are the
ones objmem.geometry uses. Copy the printed lines into your config file
(img_w, img_h, fx, fy, cx, cy, hfov).

Run on the Jetson (over SSH), with the RealSense plugged in:
  conda activate test1001
  cd ~/object-finder-bot
  export PYTHONPATH=$PWD/src
  python vision/print_intrinsics.py                     # 640x480, the default
  python vision/print_intrinsics.py --width 1280 --height 720
  python vision/print_intrinsics.py >> config/classroom.yaml   # then remove duplicate keys

For the C920 (no API for intrinsics) use --c920-hfov-deg: it prints keys from the
nominal field of view (about 70 deg horizontal for the C920 at 16:9).
"""
import argparse
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
if os.path.isdir(os.path.join(REPO, "src", "objmem")) and os.path.join(REPO, "src") not in sys.path:
    sys.path.insert(0, os.path.join(REPO, "src"))

from objmem.camera import intrinsics_to_params  # noqa: E402

KEYS = ("img_w", "img_h", "fx", "fy", "cx", "cy", "hfov")


def format_yaml(values, comment=None):
    lines = []
    if comment:
        lines.append("# " + comment)
    for key in KEYS:
        v = values[key]
        if key in ("img_w", "img_h"):
            lines.append("{}: {}".format(key, int(v)))
        elif key == "hfov":
            lines.append("{}: {:.4f}          # rad ({:.1f} deg)".format(key, v, math.degrees(v)))
        else:
            lines.append("{}: {:.2f}".format(key, v))
    return "\n".join(lines)


def from_hfov(width, height, hfov_deg):
    """Square-pixel pinhole intrinsics from a horizontal field of view."""
    fx = width / (2.0 * math.tan(math.radians(hfov_deg) / 2.0))
    return intrinsics_to_params(fx, fx, width / 2.0, height / 2.0, width, height)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Print camera intrinsics as config keys.")
    ap.add_argument("--width", type=int, default=640)
    ap.add_argument("--height", type=int, default=480)
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--c920-hfov-deg", type=float, default=None,
                    help="no RealSense: compute keys for a webcam with this horizontal FOV")
    args = ap.parse_args(argv)

    if args.c920_hfov_deg is not None:
        values = from_hfov(args.width, args.height, args.c920_hfov_deg)
        print(format_yaml(values, "webcam {}x{}, nominal hfov {} deg (estimate, not calibrated)".format(
            args.width, args.height, args.c920_hfov_deg)))
        return 0

    from objmem.camera import make_camera
    try:
        cam = make_camera("realsense", width=args.width, height=args.height, fps=args.fps)
    except ImportError:
        print("[FAIL] pyrealsense2 is not installed in this Python. Try: pip install pyrealsense2, "
              "or the librealsense build for the Jetson.", file=sys.stderr)
        return 1
    except RuntimeError as exc:
        print("[FAIL] RealSense did not start: {}. Check the USB 3 cable and `rs-enumerate-devices`.".format(exc),
              file=sys.stderr)
        return 1
    try:
        values = cam.intrinsics()
        frame = cam.read()
        print(format_yaml(values, "RealSense color {}x{} (depth aligned to color), depth scale {} m/unit".format(
            values["img_w"], values["img_h"], cam.depth_scale)))
        if frame is None:
            print("# warning: no frame arrived within the timeout", file=sys.stderr)
        else:
            d = frame.depth
            valid = d[d > 0]
            if valid.size:
                print("# depth check: {:.0%} valid pixels, median {:.2f} m".format(valid.size / float(d.size),
                                                                                 float(np.median(valid))))
    finally:
        cam.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
