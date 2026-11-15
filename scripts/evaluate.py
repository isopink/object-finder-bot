"""Evaluation tables for the report (proposal section 7).

Toy world (default; no hardware):

    python scripts/evaluate.py                    # 5 seeds x 20 queries, both cameras
    python scripts/evaluate.py --seeds 10 --out-dir out

Real run (a memory file saved by the observer plus the search log of the finder):

    python scripts/evaluate.py --memory memory.npz --log search_log.jsonl \
        --ground-truth data/ground_truth.yaml [--map maps/lab.yaml]

Prints Markdown tables and saves a map figure in --out-dir (default: out).
Success = the re-check passed and the remembered position is within 0.5 m of the truth.
"""
import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(ROOT, "src"))

from objmem.sim.evaluation import evaluate_real, evaluate_toy  # noqa: E402
from objmem.sim.runner import load_queries  # noqa: E402
from objmem.types import Params  # noqa: E402

TITLES = {
    "search": "Search success, static room (CLIP search vs fixed-class label match)",
    "moved": "After moving 4 objects and patrolling again (with vs without probabilistic memory)",
    "position": "Position error per object, top-1 candidate of the object's first query (mean over seeds)",
    "summary": "Real run: summary",
    "queries": "Real run: queries",
    "memory": "Real run: memory items",
}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seeds", type=int, default=5, help="toy world: number of seeds (0..N-1)")
    ap.add_argument("--queries", default=os.path.join(ROOT, "data", "queries.yaml"))
    ap.add_argument("--out-dir", default="out", help="where map figures go ('' = no figure)")
    ap.add_argument("--memory", default=None, help="real run: memory .npz saved by the observer")
    ap.add_argument("--log", default=None, help="real run: JSON-lines search log written by search.find")
    ap.add_argument("--ground-truth", default=os.path.join(ROOT, "data", "ground_truth.yaml"))
    ap.add_argument("--map", default=None, help="real run: map_saver .yaml for the figure")
    ap.add_argument("--config", default=None, help="real run: Params YAML (e.g. config/default.yaml)")
    args = ap.parse_args(argv)
    queries = load_queries(args.queries)
    out_dir = args.out_dir or None

    if args.memory or args.log:
        if not (args.memory and args.log):
            ap.error("a real run needs both --memory and --log")
        params = Params.load(args.config) if args.config else None
        tables = evaluate_real(args.memory, args.log, args.ground_truth, queries, params=params,
                               map_yaml=args.map, out_dir=out_dir)
        order = ["summary", "queries", "memory", "skipped", "figure"]
    else:
        seeds = list(range(args.seeds))
        print("Toy world: {} seeds x {} queries per row; success = re-check passed and position within 0.5 m.\n".format(
            len(seeds), len(queries)))
        tables = evaluate_toy(seeds, queries, out_dir=out_dir)
        order = ["search", "moved", "position", "figure_depth", "figure_nodepth"]
    for key in order:
        if key not in tables:
            continue
        if key.startswith("figure") or key == "skipped":
            print("{}: {}".format("Map figure" if key.startswith("figure") else "Note", tables[key]))
            continue
        print("### " + TITLES[key] + "\n")
        print(tables[key] + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
