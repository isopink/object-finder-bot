"""
jetson_find_object.py - mini object finder on a Jetson (camera + detectNet + CLIP memory/search).

The vision part of the object-finding robot, without the robot. A memory stores
an on-screen box here; the robot version stores a map coordinate instead.

Flow
  camera -> detectNet boxes (live view in the browser)
  s          remember the objects detected in the current frame
  t          remember the frame as 3x3 tiles (for objects detectNet does not know)
  q <text>   find the closest memory, show its box for 5 s, save a result image
  f <text>   search the current frame directly

Args    --input   camera (default v4l2:///dev/video0)
        --output  video sink (default webrtc://@:8554/mystream -> http://<JETSON-IP>:8554)
Output  browser video, terminal results, memory/ (memory file, crops, result images)

Uses the CLIP settings checked with clip_jetson_test.py (ViT-B-32, FP16).

Run (on the Jetson)
  conda activate test1001
  cd ~/uos_ir/vision
  python jetson_find_object.py
"""
import argparse
import os
import sys
import threading
import time

import numpy as np
import open_clip
import torch
from PIL import Image

from jetson_inference import detectNet
from jetson_utils import (cudaDeviceSynchronize, cudaDrawRect, cudaFont,
                          cudaToNumpy, videoOutput, videoSource)

HERE = os.path.dirname(os.path.abspath(__file__))
MEM_DIR = os.path.join(HERE, "memory")
CROP_DIR = os.path.join(MEM_DIR, "crops")
MEM_FILE = os.path.join(MEM_DIR, "memory.npz")
os.makedirs(CROP_DIR, exist_ok=True)

HELP = """
Commands (press Enter after each):
  s            remember the objects detected in the current frame
  t            remember the current frame as 3x3 tiles (for objects detectNet does not know)
  q <text>     search memory      e.g. q a cup  /  q a black bag  /  q a plastic cup with a straw
               (searches stored memories; after moving objects or the camera, save again with s or t)
  f <text>     search the current frame (nothing stored; 83 overlapping windows + detections, about 2 s)
  l            list memories
  x            clear all memories
  h            help
  exit         quit (or Ctrl+C)
"""


# ---------------------------------------------------------------- memory store
class Memory:
    """
    One memory = CLIP vector + screen box (l,t,r,b) + label + timestamp + crop path.
    The robot version stores a map coordinate (x, y) instead of the screen box.
    """

    def __init__(self):
        self.vecs, self.boxes, self.labels, self.times, self.paths = [], [], [], [], []
        if os.path.exists(MEM_FILE):
            d = np.load(MEM_FILE, allow_pickle=True)
            self.vecs = list(d["vecs"])
            self.boxes = [tuple(b) for b in d["boxes"]]
            self.labels = list(d["labels"])
            self.times = list(d["times"])
            self.paths = list(d["paths"])
            print("Loaded {} memories.".format(len(self.vecs)))

    def add(self, vec, box, label, crop_rgb):
        """Add one memory: vec (512,), box (l,t,r,b), label, crop_rgb (numpy RGB)."""
        path = os.path.join(CROP_DIR, "{}_{}.jpg".format(int(time.time() * 1000), len(self.vecs)))
        Image.fromarray(crop_rgb).save(path, quality=90)
        self.vecs.append(vec)
        self.boxes.append(tuple(int(v) for v in box))
        self.labels.append(label)
        self.times.append(time.time())
        self.paths.append(path)

    def save(self):
        np.savez(MEM_FILE, vecs=np.array(self.vecs), boxes=np.array(self.boxes), labels=np.array(self.labels),
                 times=np.array(self.times), paths=np.array(self.paths))

    def clear(self):
        self.vecs, self.boxes, self.labels, self.times, self.paths = [], [], [], [], []
        if os.path.exists(MEM_FILE):
            os.remove(MEM_FILE)


# ---------------------------------------------------------------- CLIP
class Clip:
    """CLIP (ViT-B-32, FP16) on the GPU; turns images and text into vectors."""

    def __init__(self):
        print("Loading CLIP... (about 15 s)")
        self.model, _, self.preprocess = open_clip.create_model_and_transforms(
            "ViT-B-32", pretrained="laion2b_s34b_b79k")
        self.tokenizer = open_clip.get_tokenizer("ViT-B-32")
        self.model = self.model.to("cuda").eval().half()

    @torch.no_grad()
    def images(self, crops_rgb):
        """List of crops (numpy RGB) -> (N, 512) normalized vectors."""
        x = torch.stack([self.preprocess(Image.fromarray(c)) for c in crops_rgb]).to("cuda").half()
        f = self.model.encode_image(x)
        return (f / f.norm(dim=-1, keepdim=True)).float().cpu().numpy()

    @torch.no_grad()
    def text(self, sentence):
        """Sentence -> (512,) normalized vector."""
        f = self.model.encode_text(self.tokenizer([sentence]).to("cuda"))
        return (f / f.norm(dim=-1, keepdim=True)).float().cpu().numpy()[0]


# ---------------------------------------------------------------- cropping
def detection_crops(frame_rgb, detections, net, pad=0.1):
    """
    Crop the frame along the detectNet boxes, padded by 10%.
    frame_rgb: clean frame before overlays (numpy); detections: net.Detect output.
    Returns [(crop, (l,t,r,b), label), ...].
    """
    h, w = frame_rgb.shape[:2]
    out = []
    for d in detections:
        pw, ph = (d.Right - d.Left) * pad, (d.Bottom - d.Top) * pad
        l, t = int(max(0, d.Left - pw)), int(max(0, d.Top - ph))
        r, b = int(min(w, d.Right + pw)), int(min(h, d.Bottom + ph))
        if r - l > 10 and b - t > 10:
            out.append((frame_rgb[t:b, l:r].copy(), (l, t, r, b), net.GetClassDesc(d.ClassID)))
    return out


def grid_crops(frame_rgb, n=3):
    """Split the frame into n x n tiles. Same return format as detection_crops."""
    h, w = frame_rgb.shape[:2]
    out = []
    for r in range(n):
        for c in range(n):
            l, t, rr, b = c * w // n, r * h // n, (c + 1) * w // n, (r + 1) * h // n
            out.append((frame_rgb[t:b, l:rr].copy(), (l, t, rr, b), "tile{}{}".format(r, c)))
    return out


def sliding_crops(frame_rgb, sizes=(2, 3, 4)):
    """
    Sliding windows of several sizes with 50% overlap, so objects are not cut at tile edges.
    sizes=(2, 3, 4): 9 half-size + 25 third-size + 49 quarter-size windows = 83
      (quarter-size windows keep small objects from being lost in the background)
    Same return format as grid_crops.
    """
    h, w = frame_rgb.shape[:2]
    out = []
    for n in sizes:
        cw, ch = w // n, h // n
        sx, sy = cw // 2, ch // 2          # half-window stride -> 50% overlap
        for t in range(0, h - ch + 1, sy):
            for l in range(0, w - cw + 1, sx):
                out.append((frame_rgb[t:t + ch, l:l + cw].copy(), (l, t, l + cw, t + ch), "win{}".format(n)))
    return out


# Below this best probability the object counts as not in view (robot: go to the next candidate)
FOUND_THRESHOLD = 0.5

# Background prompts the query must clearly beat for a window to count as a match
BACKGROUND_PROMPTS = [
    "a photo of a wall", "a photo of the floor", "a photo of a ceiling", "a photo of a desk",
    "a photo of a chair", "a photo of a person", "a photo of a computer monitor",
    "a photo of a keyboard", "a blurry photo of a room",
]


def live_scores(clip, vecs, query):
    """
    Probability (0-1) that each window matches the query rather than a background prompt.
    CLIP zero-shot classification: softmax over [query, background1, background2, ...].
    vecs: (N, 512) window vectors; query: text to find.
    Returns (probabilities, raw similarities to the query).
    """
    texts = [query] + [p for p in BACKGROUND_PROMPTS if p.lower() not in query.lower()]
    tvecs = np.stack([clip.text(t) for t in texts])          # (K, 512)
    logits = 100.0 * vecs @ tvecs.T                          # (N, K), CLIP default temperature 100
    logits -= logits.max(axis=1, keepdims=True)
    probs = np.exp(logits)
    probs /= probs.sum(axis=1, keepdims=True)
    return probs[:, 0], vecs @ tvecs[0]


def save_crops_image(crops_rgb, name):
    """Save the crops side by side as memory/<name>."""
    tiles = [Image.fromarray(c).resize((240, max(1, int(240 * c.shape[0] / c.shape[1])))) for c in crops_rgb]
    canvas = Image.new("RGB", (240 * len(tiles), max(t.height for t in tiles)), (40, 40, 40))
    for k, t in enumerate(tiles):
        canvas.paste(t, (240 * k, 0))
    path = os.path.join(MEM_DIR, name)
    canvas.save(path, quality=90)
    return path


def age_text(t):
    """Timestamp -> '35s ago', '4m ago'."""
    sec = int(time.time() - t)
    if sec < 60:
        return "{}s ago".format(sec)
    if sec < 3600:
        return "{}m ago".format(sec // 60)
    return "{}h ago".format(sec // 3600)


def save_result_image(memory, results, query):
    """Save the top-3 result crops side by side as memory/result.jpg."""
    tiles = []
    for sim, i in results:
        im = Image.open(memory.paths[i]).convert("RGB")
        im = im.resize((240, max(1, int(240 * im.height / im.width))))
        tiles.append(im)
    H = max(t.height for t in tiles)
    canvas = Image.new("RGB", (240 * len(tiles), H), (40, 40, 40))
    for k, t in enumerate(tiles):
        canvas.paste(t, (240 * k, 0))
    path = os.path.join(MEM_DIR, "result.jpg")
    canvas.save(path, quality=90)
    return path


# ---------------------------------------------------------------- terminal input (separate thread)
class Commands:
    """Reads terminal input into a queue while the video loop runs."""

    def __init__(self):
        self.queue = []
        self.lock = threading.Lock()
        threading.Thread(target=self._loop, daemon=True).start()

    def _loop(self):
        while True:
            try:
                line = sys.stdin.readline()
            except Exception:
                return
            if not line:
                return
            with self.lock:
                self.queue.append(line.strip())

    def pop(self):
        with self.lock:
            return self.queue.pop(0) if self.queue else None


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default="v4l2:///dev/video0")
    ap.add_argument("--output", default="webrtc://@:8554/mystream")
    ap.add_argument("--width", type=int, default=1920)
    ap.add_argument("--height", type=int, default=1080)
    ap.add_argument("--network", default="ssd-mobilenet-v2")
    ap.add_argument("--threshold", type=float, default=0.5)
    args = ap.parse_args()

    clip = Clip()
    memory = Memory()
    net = detectNet(args.network, argv=[], threshold=args.threshold)
    # Same input options as the ir-guide example (simple_mobilenet.py)
    inp = videoSource(args.input, options={"width": args.width, "height": args.height,
                                           "codec": "mjpeg", "encoder": "v4l2"})
    out = videoOutput(args.output, options={"codec": "h264", "encoder": "v4l2", "bitrate": 8000000, "latency": 30})
    font = cudaFont()
    cmds = Commands()

    print(HELP)
    print("Open http://<JETSON-IP>:8554 in a browser to see the video.")

    try:
        run_loop(args, clip, memory, net, inp, out, font, cmds)
    except KeyboardInterrupt:
        pass
    except Exception:
        import traceback
        traceback.print_exc()
        print("\nExiting on error. See the traceback above.")
    # Force exit so leftover video-server threads do not keep the process alive
    sys.stdout.flush()
    os._exit(0)


def run_loop(args, clip, memory, net, inp, out, font, cmds):
    """Per frame: handle command -> capture -> (remember) -> detect -> (show result) -> render."""
    highlight = None  # (box, text, end time)
    pending = None    # command to handle on the next frame: 's', 't', or ('f', query)
    frames, last_report, empty = 0, time.time(), 0

    while True:
        cmd = cmds.pop()
        if cmd:
            if cmd in ("exit", "quit"):
                print("Exiting.")
                return
            elif cmd in ("s", "t"):
                pending = cmd
            elif cmd == "l":
                if not memory.vecs:
                    print("Memory is empty.")
                for i, (lab, box) in enumerate(zip(memory.labels, memory.boxes)):
                    print("  #{:02d} {:12s} box {}".format(i, lab, box))
            elif cmd == "x":
                memory.clear()
                print("Memory cleared.")
            elif cmd.startswith("q "):
                query = cmd[2:].strip()
                if not memory.vecs:
                    print("Memory is empty. Save with s or t first.")
                else:
                    sims = np.array(memory.vecs) @ clip.text(query)
                    order = list(np.argsort(-sims)[:3])
                    results = [(float(sims[i]), int(i)) for i in order]
                    print("'{}' memory search (stored memories, not the current frame):".format(query))
                    for rank, (s, i) in enumerate(results, 1):
                        print("  #{} sim {:.3f}  {:12s} box {}  ({})".format(
                            rank, s, memory.labels[i], memory.boxes[i], age_text(memory.times[i])))
                    print("  result image:", save_result_image(memory, results, query))
                    best = results[0][1]
                    highlight = (memory.boxes[best], "MEMORY: {} ({:.2f}, {})".format(
                        query, results[0][0], age_text(memory.times[best])), time.time() + 5)
            elif cmd.startswith("f "):
                pending = ("f", cmd[2:].strip())
            elif cmd in ("h", "help"):
                print(HELP)
            else:
                print("Unknown command. Type h for help.")

        img = inp.Capture()
        if img is None:
            empty += 1
            if empty % 5 == 0:
                print("[diag] No frame from the camera (x{}). Check the device number and whether another program is using it.".format(empty))
            continue
        frames += 1
        if frames == 1:
            print("[diag] First frame: {}x{}. Refresh the browser now.".format(img.width, img.height))
        if time.time() - last_report > 15:
            print("[diag] {} frames processed, detectNet {:.0f} FPS".format(frames, net.GetNetworkFPS()))
            last_report = time.time()

        # For a pending command, copy the clean frame before boxes are drawn
        clean = None
        if pending:
            cudaDeviceSynchronize()
            clean = cudaToNumpy(img)[:, :, :3].copy()

        detections = net.Detect(img, overlay="box,labels,conf")

        if isinstance(pending, tuple) and clean is not None:
            # f: search the current frame (nothing is stored)
            query = pending[1]
            t0 = time.time()
            crops = detection_crops(clean, detections, net) + sliding_crops(clean)
            vecs = clip.images([c[0] for c in crops])
            score, sims = live_scores(clip, vecs, query)
            order = list(np.argsort(-score)[:3])
            print("'{}' current-frame search ({} windows, {:.1f} s):".format(query, len(crops), time.time() - t0))
            for rank, i in enumerate(order, 1):
                print("  #{} prob {:.2f} (sim {:.3f})  {:12s} box {}".format(
                    rank, float(score[i]), float(sims[i]), crops[i][2], crops[i][1]))
            print("  result image:", save_crops_image([crops[i][0] for i in order], "result_now.jpg"))
            best = order[0]
            if score[best] >= FOUND_THRESHOLD:
                print("  -> found (prob {:.2f} >= {})".format(float(score[best]), FOUND_THRESHOLD))
                highlight = (crops[best][1], "NOW: {} ({:.2f})".format(query, float(score[best])), time.time() + 5)
            else:
                # No window clearly beats the background prompts: treat as not in view
                print("  -> not found in the current frame (best prob {:.2f} < {}). It may be out of view or too small.".format(
                    float(score[best]), FOUND_THRESHOLD))
                highlight = (None, "NOT FOUND: {} (best {:.2f})".format(query, float(score[best])),
                             time.time() + 5)
            pending = None
        elif pending and clean is not None:
            crops = detection_crops(clean, detections, net) if pending == "s" else grid_crops(clean)
            if crops:
                vecs = clip.images([c[0] for c in crops])
                for (crop, box, label), vec in zip(crops, vecs):
                    memory.add(vec, box, label, crop)
                memory.save()
                print("Added {} memories: {}  (total {})".format(len(crops), [c[2] for c in crops], len(memory.vecs)))
            else:
                print("No objects detected. Try t to save tiles.")
            pending = None

        # Show the search result on screen for 5 s
        if highlight and time.time() < highlight[2]:
            if highlight[0] is None:  # not found: text only, no box
                font.OverlayText(img, img.width, img.height, highlight[1], 10, 10, font.White, font.Gray40)
            else:
                l, t, r, b = highlight[0]
                cudaDrawRect(img, (l, t, r, b), (255, 0, 255, 70))
                font.OverlayText(img, img.width, img.height, highlight[1], l + 5, t + 5, font.White, font.Gray40)
        font.OverlayText(img, img.width, img.height, "memory: {}".format(len(memory.vecs)),
                         10, img.height - 40, font.White, font.Gray40)

        out.Render(img)
        out.SetStatus("find-object | {:.0f} FPS".format(net.GetNetworkFPS()))
        if not inp.IsStreaming() or not out.IsStreaming():
            print("Video input/output ended. Exiting.")
            return


if __name__ == "__main__":
    main()
