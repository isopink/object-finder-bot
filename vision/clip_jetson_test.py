"""
clip_jetson_test.py - check that CLIP runs on a Jetson, and measure its speed and memory use.

CLIP (image-text matching) is the core of the object-finding robot. This checks
whether it runs fast enough on a Jetson Xavier NX (8 GB shared memory, Python 3.8)
to be used alongside a detector.

Steps
  1. Load CLIP (ViT-B-32) on the GPU (first run downloads about 600 MB)
  2. Embed the images in a folder and time each one (ms)
  3. Find the closest images for text queries ("an orange", "a dog", ...)
  4. Print GPU memory use

Args    --images  image folder (default: the jetson-inference sample images)
        --fp16    run in half precision (usually faster, less memory)
Output  model load time, time per image, top-3 per query, memory use

Run (on the Jetson)
  conda activate test1001
  cd ~/uos_ir/vision
  python clip_jetson_test.py
  python clip_jetson_test.py --fp16

Avoids newer syntax so it runs on Python 3.8.
"""
import argparse
import glob
import os
import time

import torch
from PIL import Image

import open_clip

DEFAULT_IMAGES = os.path.expanduser("~/jetson-inference/build/aarch64/bin/images")
DEFAULT_QUERIES = [
    "an orange",
    "a banana",
    "a dog",
    "a cat",
    "a bird",
    "a car",
    "a person",
    "a red object",
]


def find_images(folder, limit):
    """
    List the image files in a folder.
    folder: image folder; limit: max number of images.
    Returns a list of paths.
    """
    paths = []
    for ext in ("*.jpg", "*.jpeg", "*.png"):
        paths += glob.glob(os.path.join(folder, ext))
    return sorted(paths)[:limit]


def gpu_mem_mb():
    """GPU memory PyTorch uses now, and its peak, in MB."""
    return torch.cuda.memory_allocated() / 2**20, torch.cuda.max_memory_allocated() / 2**20


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--images", default=DEFAULT_IMAGES, help="image folder")
    ap.add_argument("--limit", type=int, default=40, help="max number of images")
    ap.add_argument("--model", default="ViT-B-32")
    ap.add_argument("--pretrained", default="laion2b_s34b_b79k")
    ap.add_argument("--fp16", action="store_true", help="run in FP16 (half precision)")
    args = ap.parse_args()

    if not torch.cuda.is_available():
        print("CUDA is not available. Check that the conda environment is active.")
        return
    device = "cuda"
    print("GPU:", torch.cuda.get_device_name(0))
    print("torch", torch.__version__, "| open_clip", open_clip.__version__)

    # ---- 1. load the model
    t0 = time.time()
    model, _, preprocess = open_clip.create_model_and_transforms(args.model, pretrained=args.pretrained)
    tokenizer = open_clip.get_tokenizer(args.model)
    model = model.to(device).eval()
    if args.fp16:
        model = model.half()
    torch.cuda.synchronize()
    print("\n[1] Model load: {:.1f} s  ({} / {} / {})".format(
        time.time() - t0, args.model, args.pretrained, "FP16" if args.fp16 else "FP32"))
    print("    GPU memory (model only): {:.0f} MB".format(gpu_mem_mb()[0]))

    # ---- 2. images -> vectors (timed)
    paths = find_images(args.images, args.limit)
    if not paths:
        print("No images found:", args.images)
        print("Set the image folder with --images.")
        return
    dtype = torch.float16 if args.fp16 else torch.float32

    def embed_image(path):
        """One image -> unit-length CLIP vector."""
        x = preprocess(Image.open(path).convert("RGB")).unsqueeze(0).to(device, dtype)
        with torch.no_grad():
            f = model.encode_image(x)
        return f / f.norm(dim=-1, keepdim=True)

    # Warm-up: the first few runs are slow, so they are excluded from timing
    for p in paths[:3]:
        embed_image(p)
    torch.cuda.synchronize()

    feats, times = [], []
    for p in paths:
        t = time.time()
        feats.append(embed_image(p))
        torch.cuda.synchronize()
        times.append((time.time() - t) * 1000)
    feats = torch.cat(feats)
    avg = sum(times) / len(times)
    print("\n[2] Embedded {} images: {:.1f} ms/image on average  ({:.1f} images/s)".format(len(paths), avg, 1000 / avg))

    # ---- 3. text search
    print("\n[3] Text search (top-3, cosine similarity)")
    with torch.no_grad():
        tok = tokenizer(DEFAULT_QUERIES).to(device)
        t = time.time()
        tfeat = model.encode_text(tok)
        torch.cuda.synchronize()
        text_ms = (time.time() - t) * 1000 / len(DEFAULT_QUERIES)
        tfeat = tfeat / tfeat.norm(dim=-1, keepdim=True)
        sims = (tfeat @ feats.T).float().cpu()
    for q, row in zip(DEFAULT_QUERIES, sims):
        top = row.topk(min(3, len(paths)))
        hits = ", ".join("{} ({:.2f})".format(os.path.basename(paths[i]), s) for s, i in zip(top.values, top.indices))
        print("  '{}': {}".format(q, hits))
    print("    Text embedding: {:.1f} ms/sentence on average".format(text_ms))

    # ---- 4. memory
    now, peak = gpu_mem_mb()
    print("\n[4] GPU memory (PyTorch): now {:.0f} MB / peak {:.0f} MB".format(now, peak))
    print("    Note: the Jetson shares 8 GB between CPU and GPU. Check total usage with jtop.")

    print("\n=== Summary ===")
    print("Model {} ({}), {}: image {:.1f} ms, text {:.1f} ms/sentence, peak GPU memory {:.0f} MB".format(
        args.model, args.pretrained, "FP16" if args.fp16 else "FP32", avg, text_ms, peak))


if __name__ == "__main__":
    main()
