"""bench_detector.py - detectNet vs YOLO on the Jetson: FPS, detections, memory.

Captures a set of frames first, then runs every detector on the same frames, so
the detection counts are comparable. Prints one Markdown table row per detector
(paste it into the report, proposal section 7) and the labels each one found.

Run on the Jetson (over SSH):
  conda activate test1001
  cd ~/object-finder-bot
  export PYTHONPATH=$PWD/src
  python vision/bench_detector.py                                   # C920, detectNet and YOLO
  python vision/bench_detector.py --camera realsense --frames 200
  python vision/bench_detector.py --yolo-engine ~/models/yolov8n.engine
  python vision/bench_detector.py --images ~/photos                 # a folder instead of a camera

Make the YOLO TensorRT engine once (takes several minutes on the Xavier NX):
  yolo export model=yolov8n.pt format=engine half=True imgsz=640

On a PC: python vision/bench_detector.py --camera fake --detectors fake
"""
import argparse
import collections
import glob
import os
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
if os.path.isdir(os.path.join(REPO, "src", "objmem")) and os.path.join(REPO, "src") not in sys.path:
    sys.path.insert(0, os.path.join(REPO, "src"))


def mem_used_mb():
    """System memory in use (MB) from /proc/meminfo. On the Jetson CPU and GPU share it."""
    try:
        info = {}
        with open("/proc/meminfo") as fh:
            for line in fh:
                key, value = line.split(":", 1)
                info[key] = int(value.split()[0])
        return (info["MemTotal"] - info["MemAvailable"]) / 1024.0
    except (OSError, KeyError, ValueError):
        return float("nan")


def rss_mb():
    """This process's resident memory (MB) from /proc/self/status."""
    try:
        with open("/proc/self/status") as fh:
            for line in fh:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) / 1024.0
    except OSError:
        pass
    return float("nan")


def capture_frames(camera, n, max_misses=50):
    frames, misses = [], 0
    while len(frames) < n and misses < max_misses:
        fr = camera.read()
        if fr is None:
            misses += 1
            continue
        frames.append(fr.color)
    return frames


def load_folder(folder, limit):
    from PIL import Image
    paths = []
    for ext in ("*.jpg", "*.jpeg", "*.png"):
        paths += glob.glob(os.path.join(os.path.expanduser(folder), ext))
    return [np.asarray(Image.open(p).convert("RGB")) for p in sorted(paths)[:limit]]


def bench(detector, frames, warmup=5):
    """Run the detector over the frames. Returns a dict of timings and counts."""
    for img in frames[:warmup]:
        detector.detect(img)
    times, counts, labels, confs = [], [], collections.Counter(), []
    for img in frames:
        t0 = time.time()
        boxes = detector.detect(img)
        times.append((time.time() - t0) * 1000.0)
        counts.append(len(boxes))
        for b in boxes:
            labels[b.label] += 1
            confs.append(b.conf)
    times = np.asarray(times) if times else np.zeros(1)
    return {
        "frames": len(frames),
        "ms_mean": float(times.mean()),
        "ms_p95": float(np.percentile(times, 95)),
        "fps": 1000.0 / float(times.mean()) if times.mean() > 0 else float("inf"),
        "per_frame": float(np.mean(counts)) if counts else 0.0,
        "with_any": float(np.mean([c > 0 for c in counts])) if counts else 0.0,
        "conf": float(np.mean(confs)) if confs else float("nan"),
        "labels": labels,
    }


def format_rows(rows):
    head = ["detector", "frames", "ms/frame", "p95 ms", "FPS", "boxes/frame", "frames with a box",
            "mean conf", "load (s)", "+memory (MB)"]
    lines = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    for name, r in rows:
        lines.append("| " + " | ".join([
            name, str(r["frames"]), "{:.1f}".format(r["ms_mean"]), "{:.1f}".format(r["ms_p95"]),
            "{:.1f}".format(r["fps"]), "{:.2f}".format(r["per_frame"]), "{:.0%}".format(r["with_any"]),
            "{:.2f}".format(r["conf"]), "{:.1f}".format(r["load_s"]), "{:.0f}".format(r["mem_mb"]),
        ]) + " |")
    return "\n".join(lines)


def build(name, args):
    from objmem.detectors import make_detector
    if name == "detectnet":
        return make_detector("detectnet", network=args.network, threshold=args.threshold)
    if name == "yolo":
        return make_detector("yolo", model=args.yolo_model, engine=args.yolo_engine, conf=args.threshold)
    return make_detector(name)


def main(argv=None):
    ap = argparse.ArgumentParser(description="detectNet vs YOLO: FPS, detections, memory.")
    ap.add_argument("--detectors", default="detectnet,yolo", help="comma separated: detectnet, yolo, fake")
    ap.add_argument("--camera", default="c920", choices=["c920", "realsense", "fake"])
    ap.add_argument("--input", default="/dev/video0", help="C920 device")
    ap.add_argument("--width", type=int, default=None)
    ap.add_argument("--height", type=int, default=None)
    ap.add_argument("--images", default=None, help="folder of photos instead of a camera")
    ap.add_argument("--frames", type=int, default=100)
    ap.add_argument("--threshold", type=float, default=0.5)
    ap.add_argument("--network", default="ssd-mobilenet-v2")
    ap.add_argument("--yolo-model", default="yolov8n.pt")
    ap.add_argument("--yolo-engine", default=None)
    args = ap.parse_args(argv)

    if args.images:
        frames = load_folder(args.images, args.frames)
        source = "{} photos from {}".format(len(frames), args.images)
    else:
        from objmem.camera import make_camera
        default = {"c920": (1280, 720), "realsense": (640, 480), "fake": (640, 480)}[args.camera]
        w, h = args.width or default[0], args.height or default[1]
        if args.camera == "c920":
            cam = make_camera("c920", device=args.input, width=w, height=h)
        elif args.camera == "realsense":
            cam = make_camera("realsense", width=w, height=h)
        else:
            cam = make_camera("fake", size=(w, h))
        print("Capturing {} frames from {} ({}x{}) ...".format(args.frames, args.camera, w, h))
        frames = capture_frames(cam, args.frames)
        close = getattr(cam, "close", None)
        if callable(close):
            close()
        source = "{} frames from {}".format(len(frames), args.camera)
    if not frames:
        print("[FAIL] No frames. Check the camera (ls /dev/video*) or the --images folder.")
        return 1
    print("Source:", source, "| frame size {}x{}".format(frames[0].shape[1], frames[0].shape[0]))

    rows = []
    for name in [s.strip() for s in args.detectors.split(",") if s.strip()]:
        before = mem_used_mb()
        t0 = time.time()
        try:
            det = build(name, args)
        except Exception as exc:  # missing library or model: report and go on
            print("[FAIL] {}: {}".format(name, exc))
            continue
        load_s = time.time() - t0
        print("Running {} ...".format(name))
        r = bench(det, frames)
        r["load_s"] = load_s
        r["mem_mb"] = mem_used_mb() - before
        rows.append((name, r))
        top = ", ".join("{} x{}".format(k, v) for k, v in r["labels"].most_common(8))
        print("  labels: {}".format(top or "(none)"))
        del det
    if not rows:
        return 1
    print()
    print(format_rows(rows))
    print("\n+memory = change in system memory in use after loading (CPU and GPU share it on the Jetson).")
    print("Process RSS now: {:.0f} MB".format(rss_mb()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
