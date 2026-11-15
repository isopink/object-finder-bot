"""bench_clip.py - CLIP latency and GPU memory on the Jetson, FP32 vs FP16.

Measures, for each precision:
  - model load time
  - image embedding time per batch (1 crop, 9 tiles, 83 sliding windows = one re-check)
  - text embedding time per sentence
  - GPU memory: allocated after loading, and peak

Uses objmem.embed.ClipEmbedder (OpenCLIP ViT-B-32, laion2b_s34b_b79k), the same
model the vision worker runs. Crops come from --images (a folder of photos) or
are synthetic noise when no folder is given.

Run on the Jetson (over SSH):
  conda activate test1001
  cd ~/object-finder-bot
  export PYTHONPATH=$PWD/src
  python vision/bench_clip.py                 # FP32 and FP16
  python vision/bench_clip.py --precision fp16 --images ~/jetson-inference/build/aarch64/bin/images

The first run downloads the weights (about 600 MB). The Jetson shares 8 GB
between CPU and GPU; watch the total with `jtop` or `tegrastats` in another pane.
"""
import argparse
import glob
import os
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
if os.path.isdir(os.path.join(REPO, "src", "objmem")) and os.path.join(REPO, "src") not in sys.path:
    sys.path.insert(0, os.path.join(REPO, "src"))

QUERIES = ["a red mug", "a black backpack", "a plastic water bottle", "a blue notebook",
           "a pair of scissors", "a smartphone", "a banana", "a white charger"]


def load_images(folder, limit, size=(640, 480)):
    """RGB arrays from a folder, or synthetic noise images when folder is None or empty."""
    paths = []
    if folder:
        for ext in ("*.jpg", "*.jpeg", "*.png"):
            paths += glob.glob(os.path.join(os.path.expanduser(folder), ext))
        paths = sorted(paths)[:limit]
    if paths:
        from PIL import Image
        return [np.asarray(Image.open(p).convert("RGB")) for p in paths], "{} photos from {}".format(len(paths), folder)
    rng = np.random.RandomState(0)
    w, h = size
    return [rng.randint(0, 255, (h, w, 3), dtype=np.uint8) for _ in range(max(1, min(limit, 8)))], "synthetic noise"


def make_batch(images, n, crop=224):
    """n crops (cycling through the images), each a random-ish window of the source."""
    out = []
    for i in range(n):
        img = images[i % len(images)]
        h, w = img.shape[:2]
        s = min(h, w, max(crop, min(h, w) // 2))
        y = (i * 37) % max(1, h - s + 1)
        x = (i * 53) % max(1, w - s + 1)
        out.append(img[y:y + s, x:x + s])
    return out


def timed(fn, repeat, sync):
    """Median wall time in ms over `repeat` runs, after one warm-up."""
    fn()
    sync()
    times = []
    for _ in range(repeat):
        t0 = time.time()
        fn()
        sync()
        times.append((time.time() - t0) * 1000.0)
    return float(np.median(times))


def bench_one(fp16, images, batches, repeat, device, model, pretrained):
    import torch
    from objmem.embed import ClipEmbedder

    cuda = device.startswith("cuda") and torch.cuda.is_available()

    def sync():
        if cuda:
            torch.cuda.synchronize()

    if cuda:
        torch.cuda.empty_cache()
        torch.cuda.reset_peak_memory_stats()
    t0 = time.time()
    emb = ClipEmbedder(model=model, pretrained=pretrained, fp16=fp16, device=device)
    sync()
    row = {"precision": "FP16" if emb.fp16 else "FP32", "load_s": time.time() - t0,
           "mem_model_mb": torch.cuda.memory_allocated() / 2 ** 20 if cuda else float("nan")}
    for n in batches:
        crops = make_batch(images, n)
        row["img_{}".format(n)] = timed(lambda: emb.embed_images(crops), repeat, sync)
    def texts():
        for q in QUERIES:
            emb.embed_text(q)

    row["text_ms"] = timed(texts, repeat, sync) / len(QUERIES)
    vecs = emb.embed_images(make_batch(images, 9))
    row["sanity"] = "ok" if np.all(np.isfinite(vecs)) and abs(float(np.linalg.norm(vecs[0])) - 1) < 1e-2 else "BAD"
    row["mem_peak_mb"] = torch.cuda.max_memory_allocated() / 2 ** 20 if cuda else float("nan")
    del emb
    if cuda:
        torch.cuda.empty_cache()
    return row


def format_table(rows, batches):
    head = ["precision", "load (s)"] + ["{} img (ms)".format(n) for n in batches] + \
           ["ms/img @{}".format(batches[-1]), "text (ms)", "GPU model (MB)", "GPU peak (MB)", "check"]
    lines = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    for r in rows:
        cells = [r["precision"], "{:.1f}".format(r["load_s"])]
        cells += ["{:.1f}".format(r["img_{}".format(n)]) for n in batches]
        cells += ["{:.1f}".format(r["img_{}".format(batches[-1])] / batches[-1]), "{:.1f}".format(r["text_ms"]),
                  "{:.0f}".format(r["mem_model_mb"]), "{:.0f}".format(r["mem_peak_mb"]), r["sanity"]]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description="CLIP latency and GPU memory, FP32 vs FP16.")
    ap.add_argument("--precision", default="both", choices=["both", "fp32", "fp16"])
    ap.add_argument("--images", default=None, help="folder of photos (default: synthetic images)")
    ap.add_argument("--limit", type=int, default=40)
    ap.add_argument("--batches", default="1,9,83", help="batch sizes, comma separated")
    ap.add_argument("--repeat", type=int, default=5)
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--model", default="ViT-B-32")
    ap.add_argument("--pretrained", default="laion2b_s34b_b79k")
    args = ap.parse_args(argv)

    import torch
    if args.device.startswith("cuda") and not torch.cuda.is_available():
        print("[FAIL] CUDA is not available. Activate the conda env with the Jetson PyTorch (test1001).")
        return 1
    if torch.cuda.is_available():
        print("GPU:", torch.cuda.get_device_name(0), "| torch", torch.__version__)
    batches = [int(s) for s in args.batches.split(",") if s.strip()]
    images, source = load_images(args.images, args.limit)
    print("Images:", source)
    precisions = {"both": [False, True], "fp32": [False], "fp16": [True]}[args.precision]
    rows = []
    for fp16 in precisions:
        print("Running {} ...".format("FP16" if fp16 else "FP32"))
        rows.append(bench_one(fp16, images, batches, args.repeat, args.device, args.model, args.pretrained))
    print()
    print(format_table(rows, batches))
    print("\n{} sliding windows = one re-check of a 16:9 frame (plus the detections).".format(83))
    print("Note: the Jetson shares 8 GB between CPU and GPU; check the total with jtop or tegrastats.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
