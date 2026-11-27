"""Merge the memories of one object in a saved memory file.

  python scripts/merge_memory.py robot/memory/room_l4_nav_depth.npz --config robot/config/depth.yaml \
      --merge-dist 0.2 --cos-same-label 0.5              # only prints what would be merged
  python scripts/merge_memory.py ... --out robot/memory/room_l4_nav_depth.npz   # writes the result

Two memories are merged when they are closer than --merge-dist, do not carry
different labels, and their CLIP cosine passes the gate (cos_thresh, or
--cos-same-label when both have the same label). The values default to
merge_dist and cos_thresh_same_label of --config. Stop the observer before
writing over the file it uses.
"""
import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(os.path.dirname(HERE), "src")
if os.path.isdir(SRC) and SRC not in sys.path:
    sys.path.insert(0, SRC)

from objmem.memory import ObjectMemory  # noqa: E402
from objmem.types import Params  # noqa: E402


def _table(mem):
    lines = []
    for it in mem.items:
        lines.append("  #{:<3d} {:<12s} ({:6.2f}, {:6.2f})  n_obs={:<4d} p={:.2f}".format(
            it.id, it.label or "-", float(it.mu[0]), float(it.mu[1]), it.n_obs, it.p))
    return "\n".join(lines) if lines else "  (empty)"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("memory", help="saved memory file (.npz)")
    ap.add_argument("--config", default=None, help="YAML with the objmem values (default: built-in defaults)")
    ap.add_argument("--merge-dist", type=float, default=None, help="meters; default: merge_dist of the config")
    ap.add_argument("--cos-same-label", type=float, default=None,
                    help="cosine gate for equal labels; default: cos_thresh_same_label of the config")
    ap.add_argument("--out", default=None, help="write the merged memory here (default: print only)")
    args = ap.parse_args(argv)

    params = Params.load(args.config)
    if args.merge_dist is not None:
        params.merge_dist = args.merge_dist
    if args.cos_same_label is not None:
        params.cos_thresh_same_label = args.cos_same_label
    if params.merge_dist <= 0.0:
        ap.error("merge_dist is 0: give --merge-dist or set merge_dist in the config")

    mem = ObjectMemory.load(args.memory, params)
    print("before: {} memories".format(len(mem.items)))
    print(_table(mem))
    merged = mem.merge_duplicates()
    for kept, removed in merged:
        print("merged #{} into #{}".format(removed, kept))
    print("after: {} memories (merge_dist={} m, cosine gate {} / same label {})".format(
        len(mem.items), params.merge_dist, params.cos_thresh, params.cos_thresh_same_label or params.cos_thresh))
    print(_table(mem))
    if args.out:
        mem.save(args.out)
        print("written: {}".format(args.out))
    elif merged:
        print("nothing written (no --out)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
