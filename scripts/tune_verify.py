"""Tune found_thresh for the re-check: run it on photos of known objects.

Photos are named by object: blue_mug.jpg, blue_mug_2.jpg, red_book-1.png ...
(a trailing _<n> or -<n> is dropped, so both are object "blue_mug").
Each query is NAME=TEXT, where NAME is the object the text describes.

  python scripts/tune_verify.py --photos photos/ \
      --query blue_mug="a blue mug" --query red_book="a red book"
  python scripts/tune_verify.py --photos photos/ --queries queries.yaml   # {blue_mug: "a blue mug", ...}

Prints the re-check probability for every photo and query, then the hit rate
(query names the object in the photo, and it is found) and the false-alarm rate
(query names another object, and it is "found") for thresholds 0.3 to 0.7.
A query given as plain TEXT (no NAME=) is printed but not counted in the rates.

Runs CLIP (OpenCLIP ViT-B-32) by default; --fake uses FakeEmbedder (for a PC check only).
--detector detectnet|yolo adds detector boxes to the sliding windows (default: windows only).
"""
import argparse
import os
import re
import sys
from typing import Dict, List, Optional, Sequence, Tuple

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(os.path.dirname(HERE), "src")
if os.path.isdir(SRC) and SRC not in sys.path:
    sys.path.insert(0, SRC)

from objmem.types import Params  # noqa: E402

IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".bmp")
THRESHOLDS = (0.3, 0.4, 0.5, 0.6, 0.7)


def object_name(path: str) -> str:
    stem = os.path.splitext(os.path.basename(path))[0]
    return re.sub(r"[_-]\d+$", "", stem)


def list_photos(folder: str) -> List[str]:
    return sorted(os.path.join(folder, n) for n in os.listdir(folder) if n.lower().endswith(IMAGE_EXTS))


def parse_queries(items: Sequence[str], path: Optional[str]) -> List[Tuple[Optional[str], str]]:
    out = []  # type: List[Tuple[Optional[str], str]]
    if path:
        import yaml
        with open(path, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
        for name, text in data.items():
            if isinstance(text, (list, tuple)):
                out.extend((str(name), str(t)) for t in text)
            else:
                out.append((str(name), str(text)))
    for item in items or []:
        if "=" in item:
            name, text = item.split("=", 1)
            out.append((name.strip(), text.strip().strip('"').strip("'")))
        else:
            out.append((None, item.strip()))
    return out


def compute_rates(rows: Sequence[Tuple[str, Optional[str], float]], thresholds=THRESHOLDS) -> List[Dict]:
    """rows: (photo object, query object or None, probability).

    Returns one dict per threshold: thresh, hits, positives, hit_rate, false_alarms, negatives, fa_rate.
    """
    out = []
    pos = [p for obj, q, p in rows if q is not None and q == obj]
    neg = [p for obj, q, p in rows if q is not None and q != obj]
    for th in thresholds:
        hits = sum(1 for p in pos if p >= th)
        fas = sum(1 for p in neg if p >= th)
        out.append({
            "thresh": th, "hits": hits, "positives": len(pos),
            "hit_rate": hits / len(pos) if pos else float("nan"),
            "false_alarms": fas, "negatives": len(neg),
            "fa_rate": fas / len(neg) if neg else float("nan"),
        })
    return out


def load_rgb(path: str):
    import numpy as np
    from PIL import Image
    with Image.open(path) as im:
        return np.asarray(im.convert("RGB"), dtype=np.uint8).copy()


def format_rates(rates: List[Dict]) -> str:
    lines = ["| found_thresh | hit rate | false-alarm rate |", "|---|---|---|"]
    for r in rates:
        lines.append("| {:.1f} | {:.2f} ({}/{}) | {:.2f} ({}/{}) |".format(
            r["thresh"], r["hit_rate"], r["hits"], r["positives"],
            r["fa_rate"], r["false_alarms"], r["negatives"]))
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--photos", required=True, help="folder of photos named by object")
    ap.add_argument("--query", action="append", default=[], help='NAME=TEXT, e.g. blue_mug="a blue mug" (repeatable)')
    ap.add_argument("--queries", default=None, help="YAML mapping NAME -> TEXT (or list of TEXT)")
    ap.add_argument("--config", default=None)
    ap.add_argument("--fake", action="store_true", help="FakeEmbedder instead of CLIP")
    ap.add_argument("--detector", default="none", choices=["none", "detectnet", "yolo"])
    ap.add_argument("--max-side", type=int, default=1280, help="downscale photos so the longer side is at most this")
    args = ap.parse_args(argv)

    import numpy as np
    from objmem.verify import score_frame

    params = Params.load(args.config)
    queries = parse_queries(args.query, args.queries)
    if not queries:
        ap.error("give at least one --query or --queries")
    photos = list_photos(args.photos)
    if not photos:
        ap.error("no photos in {}".format(args.photos))

    if args.fake:
        from objmem.embed import FakeEmbedder
        embedder = FakeEmbedder()
    else:
        from objmem.embed import ClipEmbedder
        embedder = ClipEmbedder()
    from objmem.embed import CachedTextEmbedder
    embedder = CachedTextEmbedder(embedder)
    detector = None
    if args.detector != "none":
        from objmem.detectors import make_detector
        detector = make_detector(args.detector)

    rows = []
    print("| photo | object | query | prob | found@{} |".format(params.found_thresh))
    print("|---|---|---|---|---|")
    for path in photos:
        color = load_rgb(path)
        h, w = color.shape[:2]
        if max(h, w) > args.max_side:
            from PIL import Image
            s = args.max_side / float(max(h, w))
            color = np.asarray(Image.fromarray(color).resize((int(w * s), int(h * s))))
        boxes = detector.detect(color) if detector is not None else []
        obj = object_name(path)
        for qname, text in queries:
            _, probs, _ = score_frame(color, boxes, text, embedder, params)
            prob = float(probs.max()) if len(probs) else 0.0
            rows.append((obj, qname, prob))
            print("| {} | {} | {} | {:.3f} | {} |".format(
                os.path.basename(path), obj, text, prob, "yes" if prob >= params.found_thresh else "no"))
    print()
    print(format_rates(compute_rates(rows)))
    return rows


if __name__ == "__main__":
    main()
