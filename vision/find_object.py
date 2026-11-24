"""find_object.py - camera-only object finder on the Jetson (camera + detector + CLIP).

The vision half of the robot without the robot: a memory entry here is an
on-screen box; on the robot it is a map position (objmem.memory).

Terminal commands (press Enter after each):
  s          remember the objects detected in the current frame
  t          remember the current frame as 3x3 tiles (for objects the detector does not know)
  q <text>   search the memories, show the best box for 5 s, save a result image
  f <text>   search the current frame directly (detections + 83 sliding windows, the robot's re-check)
  l          list memories
  x          clear all memories
  h          help
  exit       quit (or Ctrl+C)

Video goes to WebRTC (default webrtc://@:8554/mystream -> open http://<JETSON-IP>:8554).

Run on the Jetson (over SSH):
  conda activate test1001
  cd ~/object-finder-bot
  export PYTHONPATH=$PWD/src
  python vision/find_object.py                                   # C920, detectNet
  python vision/find_object.py --camera realsense --detector yolo --yolo-engine yolov8n.engine

Run on a PC with no hardware (fakes, no video):
  python vision/find_object.py --fake --output none
"""
import argparse
import os
import sys
import threading
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
if os.path.isdir(os.path.join(REPO, "src", "objmem")) and os.path.join(REPO, "src") not in sys.path:
    sys.path.insert(0, os.path.join(REPO, "src"))

from objmem.crops import detection_crops, grid_crops  # noqa: E402
from objmem.types import Params  # noqa: E402
from objmem.verify import score_frame  # noqa: E402

HELP = """
Commands (press Enter after each):
  s            remember the objects detected in the current frame
  t            remember the current frame as 3x3 tiles (for objects the detector does not know)
  q <text>     search memory      e.g. q a cup  /  q a black bag  /  q a plastic cup with a straw
               (searches stored memories; after moving objects or the camera, save again with s or t)
  f <text>     search the current frame (nothing stored; detections + 83 overlapping windows, about 2 s)
  l            list memories
  x            clear all memories
  h            help
  exit         quit (or Ctrl+C)
"""

DEFAULT_SIZES = {"c920": (1920, 1080), "realsense": (640, 480), "fake": (1280, 720)}
HIGHLIGHT_S = 5.0


# ---------------------------------------------------------------- memory store
class ScreenMemory(object):
    """One memory = CLIP vector + screen box (l, t, r, b) + label + timestamp + crop path.

    Stored in <dir>/memory.npz, crops in <dir>/crops/.
    """

    def __init__(self, directory, save_crops=True):
        self.dir = directory
        self.crop_dir = os.path.join(directory, "crops")
        self.file = os.path.join(directory, "memory.npz")
        self.save_crops = save_crops
        os.makedirs(self.crop_dir, exist_ok=True)
        self.vecs, self.boxes, self.labels, self.times, self.paths = [], [], [], [], []
        if os.path.exists(self.file):
            d = np.load(self.file, allow_pickle=False)
            self.vecs = [np.asarray(v, np.float32) for v in d["vecs"]]
            self.boxes = [tuple(int(v) for v in b) for b in d["boxes"]]
            self.labels = [str(s) for s in d["labels"]]
            self.times = [float(t) for t in d["times"]]
            self.paths = [str(p) for p in d["paths"]]
            print("Loaded {} memories from {}.".format(len(self.vecs), self.file))

    def __len__(self):
        return len(self.vecs)

    def add(self, vec, box, label, crop_rgb):
        path = ""
        if self.save_crops:
            path = os.path.join(self.crop_dir, "{}_{}.jpg".format(int(time.time() * 1000), len(self.vecs)))
            save_jpeg(crop_rgb, path)
        self.vecs.append(np.asarray(vec, np.float32))
        self.boxes.append(tuple(int(v) for v in box))
        self.labels.append(str(label))
        self.times.append(time.time())
        self.paths.append(path)

    def save(self):
        vecs = np.stack(self.vecs).astype(np.float32) if self.vecs else np.zeros((0, 512), np.float32)
        np.savez(self.file, vecs=vecs,
                 boxes=np.array(self.boxes, np.int64).reshape(len(self.boxes), 4),
                 labels=np.array(self.labels, dtype=str), times=np.array(self.times, np.float64),
                 paths=np.array(self.paths, dtype=str))

    def clear(self):
        self.vecs, self.boxes, self.labels, self.times, self.paths = [], [], [], [], []
        if os.path.exists(self.file):
            os.remove(self.file)

    def search(self, text_vec, k=3):
        """Top-k (similarity, index) by cosine similarity."""
        if not self.vecs:
            return []
        sims = np.stack(self.vecs) @ np.asarray(text_vec, np.float32)
        order = list(np.argsort(-sims)[:k])
        return [(float(sims[i]), int(i)) for i in order]


def save_jpeg(rgb, path):
    """Save an RGB array as JPEG (PIL). Silently skipped when PIL is missing."""
    try:
        from PIL import Image
    except ImportError:
        return None
    Image.fromarray(np.ascontiguousarray(rgb)).save(path, quality=90)
    return path


def save_strip(crops_rgb, path, tile_w=240):
    """Save crops side by side as one JPEG. Returns the path, or None without PIL or crops."""
    try:
        from PIL import Image
    except ImportError:
        return None
    images = []
    for c in crops_rgb:
        if isinstance(c, str):
            if not c or not os.path.exists(c):
                continue
            im = Image.open(c).convert("RGB")
        else:
            im = Image.fromarray(np.ascontiguousarray(c))
        images.append(im.resize((tile_w, max(1, int(tile_w * im.height / max(1, im.width))))))
    if not images:
        return None
    canvas = Image.new("RGB", (tile_w * len(images), max(t.height for t in images)), (40, 40, 40))
    for k, im in enumerate(images):
        canvas.paste(im, (tile_w * k, 0))
    canvas.save(path, quality=90)
    return path


def age_text(t, now=None):
    sec = int((time.time() if now is None else now) - t)
    if sec < 60:
        return "{}s ago".format(sec)
    if sec < 3600:
        return "{}m ago".format(sec // 60)
    return "{}h ago".format(sec // 3600)


# ---------------------------------------------------------------- the app (no video code)
class FinderApp(object):
    """Commands and per-frame work. Video output is separate (VideoOut), so this runs anywhere."""

    def __init__(self, embedder, detector, memory, params, out_dir, log=print):
        self.embedder = embedder
        self.detector = detector
        self.memory = memory
        self.params = params
        self.out_dir = out_dir
        self.log = log
        self.pending = None    # 's', 't', or ('f', query): handled on the next frame
        self.highlight = None  # (box or None, text, end time)
        self.last_boxes = []
        self.last_result = None  # result of the last q / f, for tests and scripts

    # ---- commands
    def command(self, cmd):
        """Handle one terminal line. Returns False when the program should exit."""
        cmd = (cmd or "").strip()
        if not cmd:
            return True
        if cmd in ("exit", "quit"):
            self.log("Exiting.")
            return False
        if cmd in ("s", "t"):
            self.pending = cmd
        elif cmd == "l":
            if not len(self.memory):
                self.log("Memory is empty.")
            for i, (lab, box, t) in enumerate(zip(self.memory.labels, self.memory.boxes, self.memory.times)):
                self.log("  #{:02d} {:12s} box {}  ({})".format(i, lab, box, age_text(t)))
        elif cmd == "x":
            self.memory.clear()
            self.log("Memory cleared.")
        elif cmd.startswith("q "):
            self.query_memory(cmd[2:].strip())
        elif cmd.startswith("f "):
            self.pending = ("f", cmd[2:].strip())
        elif cmd in ("h", "help"):
            self.log(HELP)
        else:
            self.log("Unknown command. Type h for help.")
        return True

    def query_memory(self, query):
        if not len(self.memory):
            self.log("Memory is empty. Save with s or t first.")
            self.last_result = []
            return []
        results = self.memory.search(self.embedder.embed_text(query), k=3)
        self.log("'{}' memory search (stored memories, not the current frame):".format(query))
        for rank, (s, i) in enumerate(results, 1):
            self.log("  #{} sim {:.3f}  {:12s} box {}  ({})".format(
                rank, s, self.memory.labels[i], self.memory.boxes[i], age_text(self.memory.times[i])))
        path = save_strip([self.memory.paths[i] for _, i in results], os.path.join(self.out_dir, "result.jpg"))
        if path:
            self.log("  result image: " + path)
        best = results[0][1]
        self.highlight = (self.memory.boxes[best], "MEMORY: {} ({:.2f}, {})".format(
            query, results[0][0], age_text(self.memory.times[best])), time.time() + HIGHLIGHT_S)
        self.last_result = results
        return results

    # ---- per frame
    def step(self, color):
        """Run the detector on one RGB frame and handle a pending s / t / f. Returns the boxes."""
        boxes = self.detector.detect(color)
        self.last_boxes = boxes
        pending, self.pending = self.pending, None
        if pending == "s" or pending == "t":
            self.remember(color, boxes, tiles=(pending == "t"))
        elif isinstance(pending, tuple):
            self.search_frame(color, boxes, pending[1])
        return boxes

    def remember(self, color, boxes, tiles=False):
        crops = grid_crops(color) if tiles else detection_crops(color, boxes, pad=float(self.params.crop_pad))
        if not crops:
            self.log("No objects detected. Try t to save tiles.")
            return 0
        vecs = self.embedder.embed_images([c.image for c in crops])
        for c, vec in zip(crops, vecs):
            self.memory.add(vec, c.box, c.label, c.image)
        self.memory.save()
        self.log("Added {} memories: {}  (total {})".format(len(crops), [c.label for c in crops], len(self.memory)))
        return len(crops)

    def search_frame(self, color, boxes, query):
        t0 = time.time()
        crops, probs, sims = score_frame(color, boxes, query, self.embedder, self.params)
        if len(crops) == 0:
            self.log("No windows to search.")
            self.last_result = (False, 0.0, None)
            return self.last_result
        order = list(np.argsort(-probs)[:3])
        self.log("'{}' current-frame search ({} windows, {:.1f} s):".format(query, len(crops), time.time() - t0))
        for rank, i in enumerate(order, 1):
            self.log("  #{} prob {:.2f} (sim {:.3f})  {:12s} box {}".format(
                rank, float(probs[i]), float(sims[i]), crops[i].label, tuple(crops[i].box)))
        path = save_strip([crops[i].image for i in order], os.path.join(self.out_dir, "result_now.jpg"))
        if path:
            self.log("  result image: " + path)
        best = order[0]
        prob = float(probs[best])
        thresh = float(self.params.found_thresh)
        if prob >= thresh:
            self.log("  -> found (prob {:.2f} >= {})".format(prob, thresh))
            self.highlight = (tuple(crops[best].box), "NOW: {} ({:.2f})".format(query, prob), time.time() + HIGHLIGHT_S)
            self.last_result = (True, prob, tuple(crops[best].box))
        else:
            self.log("  -> not found in the current frame (best prob {:.2f} < {}). "
                     "It may be out of view or too small.".format(prob, thresh))
            self.highlight = (None, "NOT FOUND: {} (best {:.2f})".format(query, prob), time.time() + HIGHLIGHT_S)
            self.last_result = (False, prob, None)
        return self.last_result

    def overlay(self, now=None):
        """What to draw: (detector boxes, highlight or None, status text)."""
        now = time.time() if now is None else now
        hl = self.highlight if self.highlight and now < self.highlight[2] else None
        return self.last_boxes, hl, "memory: {}".format(len(self.memory))


# ---------------------------------------------------------------- video output (jetson_utils)
class VideoOut(object):
    """Renders RGB frames with boxes to a jetson_utils videoOutput (WebRTC by default).

    uri "none" disables video (terminal only).
    """

    def __init__(self, uri, bitrate=8000000):
        self.enabled = uri not in ("none", "", None)
        if not self.enabled:
            return
        import jetson_utils
        self.ju = jetson_utils
        self.out = jetson_utils.videoOutput(uri, options={"codec": "h264", "encoder": "v4l2",
                                                          "bitrate": bitrate, "latency": 30})
        self.font = jetson_utils.cudaFont()

    def render(self, color, boxes, highlight, status, fps_text=""):
        if not self.enabled:
            return True
        ju, font = self.ju, self.font
        img = ju.cudaFromNumpy(np.ascontiguousarray(color))
        for b in boxes:
            l, t, r, bt = b.box
            ju.cudaDrawRect(img, (l, t, r, bt), (0, 255, 0, 40))
            font.OverlayText(img, img.width, img.height, "{} {:.0%}".format(b.label, b.conf),
                             l + 3, t + 3, font.White, font.Gray40)
        if highlight:
            box, text, _ = highlight
            if box is None:
                font.OverlayText(img, img.width, img.height, text, 10, 10, font.White, font.Gray40)
            else:
                l, t, r, bt = box
                ju.cudaDrawRect(img, (l, t, r, bt), (255, 0, 255, 70))
                font.OverlayText(img, img.width, img.height, text, l + 5, t + 5, font.White, font.Gray40)
        font.OverlayText(img, img.width, img.height, status, 10, img.height - 40, font.White, font.Gray40)
        self.out.Render(img)
        self.out.SetStatus("find-object | {}".format(fps_text))
        return self.out.IsStreaming()


# ---------------------------------------------------------------- terminal input thread
class Commands(object):
    """Reads terminal lines into a queue while the video loop runs."""

    def __init__(self, stream=None):
        self.stream = stream or sys.stdin
        self.queue = []
        self.lock = threading.Lock()
        self.closed = False
        threading.Thread(target=self._loop, daemon=True).start()

    def _loop(self):
        while True:
            try:
                line = self.stream.readline()
            except Exception:
                line = ""
            if not line:
                self.closed = True
                return
            with self.lock:
                self.queue.append(line.strip())

    def pop(self):
        with self.lock:
            return self.queue.pop(0) if self.queue else None


# ---------------------------------------------------------------- building the parts
def parse_args(argv=None):
    ap = argparse.ArgumentParser(description="Camera-only object finder (camera + detector + CLIP).")
    ap.add_argument("--camera", default="c920", choices=["c920", "realsense", "fake"])
    ap.add_argument("--input", default="/dev/video0", help="C920 device (/dev/videoN or a jetson_utils URI)")
    ap.add_argument("--backend", default="auto", choices=["auto", "jetson", "opencv"], help="C920 reader")
    ap.add_argument("--width", type=int, default=None, help="default 1920 (C920), 640 (RealSense)")
    ap.add_argument("--height", type=int, default=None, help="default 1080 (C920), 480 (RealSense)")
    ap.add_argument("--output", default="webrtc://@:8554/mystream", help='video sink, or "none"')
    ap.add_argument("--detector", default="detectnet", choices=["detectnet", "yolo", "owl", "fake"])
    ap.add_argument("--network", default="ssd-mobilenet-v2", help="detectNet model")
    ap.add_argument("--threshold", type=float, default=0.5, help="detector confidence threshold")
    ap.add_argument("--yolo-model", default="yolov8n.pt")
    ap.add_argument("--yolo-engine", default=None, help="TensorRT .engine file for YOLO")
    ap.add_argument("--owl-engine", default=None, help="NanoOWL image encoder engine (default ~/nanoowl/data/...)")
    ap.add_argument("--owl-prompts", default=None, help="comma separated phrases for --detector owl")
    ap.add_argument("--config", default=None, help="config/default.yaml (found_thresh, crop_pad, prompts)")
    ap.add_argument("--memory-dir", default=os.path.join(HERE, "memory"))
    ap.add_argument("--fake", action="store_true",
                    help="FakeEmbedder + fake camera + fake detector, runs on a PC")
    ap.add_argument("--fake-clip", action="store_true", help="FakeEmbedder instead of CLIP")
    ap.add_argument("--max-frames", type=int, default=0, help="stop after this many frames (0 = run forever)")
    args = ap.parse_args(argv)
    if args.fake:
        args.camera, args.detector, args.fake_clip = "fake", "fake", True
    return args


def build_parts(args):
    """(embedder, detector, camera, params) from the arguments."""
    from objmem.camera import make_camera
    from objmem.detectors import make_detector

    params = Params.load(args.config)
    if args.fake_clip:
        from objmem.embed import FakeEmbedder
        embedder = FakeEmbedder()
    else:
        from objmem.embed import ClipEmbedder
        print("Loading CLIP (ViT-B-32, FP16)... about 15 s")
        embedder = ClipEmbedder()
    try:
        from objmem.embed import CachedTextEmbedder
        embedder = CachedTextEmbedder(embedder)
    except ImportError:
        pass
    w, h = DEFAULT_SIZES[args.camera]
    w, h = args.width or w, args.height or h
    if args.camera == "c920":
        camera = make_camera("c920", device=args.input, width=w, height=h, backend=args.backend)
    elif args.camera == "realsense":
        camera = make_camera("realsense", width=w, height=h)
    else:
        camera = make_camera("fake", mode="depth", size=(w, h))
    if args.detector == "detectnet":
        detector = make_detector("detectnet", network=args.network, threshold=args.threshold)
    elif args.detector == "yolo":
        detector = make_detector("yolo", model=args.yolo_model, engine=args.yolo_engine, conf=args.threshold)
    elif args.detector == "owl":
        owl_kw = {}
        if args.owl_engine:
            owl_kw["engine"] = args.owl_engine
        if args.owl_prompts:
            owl_kw["prompts"] = [s for s in args.owl_prompts.split(",") if s.strip()]
        # detectNet's 0.5 default would drop most OWL boxes; OWL scores run lower.
        thr = args.threshold if args.threshold != 0.5 else 0.15
        detector = make_detector("owl", threshold=thr, **owl_kw)
    else:
        detector = make_detector("fake")
    return embedder, detector, camera, params


def run_loop(app, camera, video, cmds, max_frames=0):
    frames, empty, last_report, t_start = 0, 0, time.time(), time.time()
    while True:
        cmd = cmds.pop()
        if cmd is not None and not app.command(cmd):
            return frames
        frame = camera.read()
        if frame is None:
            empty += 1
            if empty % 5 == 0:
                print("[diag] No frame from the camera (x{}). Check the device and whether "
                      "another program is using it.".format(empty))
            continue
        frames += 1
        if frames == 1:
            print("[diag] First frame: {}x{}. Refresh the browser now.".format(frame.color.shape[1], frame.color.shape[0]))
        app.step(frame.color)
        fps = getattr(app.detector, "fps", None)
        fps_text = "{:.0f} FPS".format(fps()) if callable(fps) else ""
        if time.time() - last_report > 15:
            print("[diag] {} frames, {:.1f} frames/s overall, detector {}".format(
                frames, frames / max(1e-6, time.time() - t_start), fps_text or "n/a"))
            last_report = time.time()
        boxes, hl, status = app.overlay()
        if not video.render(frame.color, boxes, hl, status, fps_text):
            print("Video output ended. Exiting.")
            return frames
        if max_frames and frames >= max_frames:
            return frames
        if cmds.closed and not cmds.queue and not video.enabled:
            # stdin closed (piped input) and no video: finish the pending command, then stop
            if app.pending is None:
                return frames


def main(argv=None):
    args = parse_args(argv)
    embedder, detector, camera, params = build_parts(args)
    memory = ScreenMemory(args.memory_dir)
    app = FinderApp(embedder, detector, memory, params, args.memory_dir)
    video = VideoOut(args.output)
    cmds = Commands()
    print(HELP)
    if video.enabled:
        print("Open http://<JETSON-IP>:8554 in a browser to see the video.")
    code = 0
    try:
        run_loop(app, camera, video, cmds, args.max_frames)
    except KeyboardInterrupt:
        pass
    except Exception:
        import traceback
        traceback.print_exc()
        print("\nExiting on error. See the traceback above.")
        code = 1
    close = getattr(camera, "close", None)
    if callable(close):
        close()
    sys.stdout.flush()
    if video.enabled:
        os._exit(code)  # leftover WebRTC server threads would keep the process alive
    return code


if __name__ == "__main__":
    sys.exit(main())
