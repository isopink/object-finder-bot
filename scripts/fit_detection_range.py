"""Measure P(detect | present) by distance from an evidence log of the robot.

robot/objmem.sh writes <log dir>/evidence.jsonl: one line per frame with every remembered
place the camera looked at, its distance, and whether the object was found there.

  python scripts/fit_detection_range.py robot/logs/<run>/evidence.jsonl --label cup
  python scripts/fit_detection_range.py <log> [<log> ...] --label cup --label laptop \
      --config robot/config/depth.yaml --compare [--write-config robot/config/depth.yaml]

On the robot, ./robot/fit_detection.sh does this for the newest run.

Prints the share of looks that found the object, per distance bin, and the d_by_range
line for robot/config/<mode>.yaml. Count only objects that stayed in place for the whole
run (--label or --ids): a look at a place the object has left is not a miss of the detector.
The looks of one drive are a few centimeters apart, so the 95 % intervals are too narrow.

--write-config puts the table into that YAML file (the d_by_range line). It refuses when
fewer than two bins have enough looks, or when no bin finds the object in at least half
of its looks: then the object was probably not where the memory has it.

--compare replays every log twice, with the one number d of the config and with the table
(the fitted one, or d_by_range of the config when it has one), and prints how p of every
memory would have moved. The replay knows the looks only: no re-check, no merging.
"""
import argparse
import json
import math
import os
import re
import sys
import time
from typing import Dict, List, Optional, Sequence, Tuple

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(os.path.dirname(HERE), "src")
if os.path.isdir(SRC) and SRC not in sys.path:
    sys.path.insert(0, SRC)

from objmem.memory import bayes_negative, bayes_positive, detect_prob, time_decay  # noqa: E402
from objmem.types import Params  # noqa: E402

DEFAULT_EDGES = (0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0)


def read_log(path: str) -> List[dict]:
    out = []
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def wanted(row: dict, labels: Sequence[str], ids: Sequence[int]) -> bool:
    if ids and int(row["id"]) in ids:
        return True
    if labels and (row.get("label") or "").lower() in labels:
        return True
    return not labels and not ids


def count(frames: Sequence[dict], edges: Sequence[float], labels: Sequence[str] = (),
          ids: Sequence[int] = ()) -> List[Tuple[float, int, int]]:
    """(upper edge, looks, found) per bin. The look that made a memory is not counted."""
    edges = sorted(float(e) for e in edges)
    n = [0] * len(edges)
    k = [0] * len(edges)
    for fr in frames:
        for row in fr.get("items", []):
            if row.get("new") or not wanted(row, labels, ids):
                continue
            for b, upper in enumerate(edges):
                if float(row["r"]) <= upper:
                    n[b] += 1
                    k[b] += int(row["hit"])
                    break
    return [(edges[b], n[b], k[b]) for b in range(len(edges))]


def wilson(k: int, n: int, z: float = 1.96) -> Tuple[float, float]:
    if n == 0:
        return 0.0, 1.0
    ph = k / float(n)
    den = 1.0 + z * z / n
    mid = (ph + z * z / (2 * n)) / den
    half = z * math.sqrt(ph * (1 - ph) / n + z * z / (4.0 * n * n)) / den
    return max(0.0, mid - half), min(1.0, mid + half)


def table_rows(counts: Sequence[Tuple[float, int, int]], min_looks: int) -> List[List[float]]:
    """d_by_range rows from the bins with at least min_looks looks; rates kept inside [0.02, 0.98]."""
    return [[upper, round(min(0.98, max(0.02, k / float(n))), 2)] for upper, n, k in counts if n >= min_looks]


def table_problem(rows: Sequence[Sequence[float]]) -> Optional[str]:
    """Why this table should not go into the config, or None."""
    if len(rows) < 2:
        return "fewer than two distance bins have enough looks"
    if max(v for _, v in rows) < 0.5:
        return "no bin finds the object in half of its looks: was it where the memory has it?"
    return None


def write_config(path: str, rows: Sequence[Sequence[float]], note: str) -> None:
    """Replace (or add after the `d:` line) the d_by_range line of a flat YAML config."""
    line = "d_by_range: [{}]  # rows [up to this distance (m), P(detect | present)]; {}; [] = d everywhere".format(
        ", ".join("[{}, {}]".format(u, v) for u, v in rows), note)
    with open(path, "r", encoding="utf-8") as fh:
        text = fh.read()
    if re.search(r"^d_by_range:.*$", text, flags=re.M):
        text = re.sub(r"^d_by_range:.*$", lambda _m: line, text, count=1, flags=re.M)
    elif re.search(r"^d:.*$", text, flags=re.M):
        text = re.sub(r"^(d:.*)$", lambda m: m.group(1) + "\n" + line, text, count=1, flags=re.M)
    else:
        text = line + "\n" + text
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(text)
    os.replace(tmp, path)


def replay(frames: Sequence[dict], params: Params) -> Dict[int, dict]:
    """p of every memory if the looks of the log had been counted with `params`
    (d or d_by_range, f, tau, p_init, p_update_dist)."""
    state = {}  # type: Dict[int, dict]
    for fr in frames:
        t, xy = float(fr["t"]), (float(fr["pose"][0]), float(fr["pose"][1]))
        for row in fr.get("items", []):
            i = int(row["id"])
            s = state.get(i)
            if s is None:
                state[i] = {"label": row.get("label"), "p": float(params.p_init), "t": t, "xy": xy,
                            "min": float(params.p_init), "looks": 0, "hits": 0, "counted": 0}
                continue
            s["p"] = time_decay(s["p"], t - s["t"], params.tau)
            s["t"] = t
            s["looks"] += 1
            s["hits"] += int(row["hit"])
            if params.p_update_dist <= 0 or math.hypot(xy[0] - s["xy"][0], xy[1] - s["xy"][1]) >= params.p_update_dist:
                d = detect_prob(float(row["r"]), params)
                s["p"] = (bayes_positive if row["hit"] else bayes_negative)(s["p"], d, params.f)
                s["xy"] = xy
                s["counted"] += 1
            s["min"] = min(s["min"], s["p"])
    return state


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("log", nargs="+", help="evidence.jsonl of one run (several: counted together)")
    ap.add_argument("--label", action="append", default=[], help="count memories with this label (repeatable)")
    ap.add_argument("--ids", default="", help="count these memory ids, comma separated")
    ap.add_argument("--edges", default=",".join(str(e) for e in DEFAULT_EDGES),
                    help="upper edges of the distance bins (m), comma separated")
    ap.add_argument("--min-looks", type=int, default=30, help="bins with fewer looks stay out of the table")
    ap.add_argument("--config", default=None, help="YAML with the objmem values (for --compare)")
    ap.add_argument("--compare", action="store_true", help="replay the log with d and with the table")
    ap.add_argument("--write-config", default=None, help="write the table into this YAML config")
    args = ap.parse_args(argv)

    labels = [s.lower() for s in args.label]
    ids = [int(s) for s in args.ids.split(",") if s.strip()]
    edges = [float(s) for s in args.edges.split(",") if s.strip()]
    runs = [(path, read_log(path)) for path in args.log]
    frames = [fr for _, run in runs for fr in run]
    counts = count(frames, edges, labels, ids)
    total = sum(n for _, n, _ in counts)
    print("{} frames, {} looks counted ({})".format(
        len(frames), total, ", ".join(labels + ["#%d" % i for i in ids]) or "every memory"))
    if not labels and not ids:
        print("NOTE: every memory is counted, also those of objects that were moved or never existed.")
    print("distance (m) | looks | found | P(detect) | 95 % interval")
    lower = 0.0
    for upper, n, k in counts:
        lo, hi = wilson(k, n)
        rate = "{:.2f}".format(k / float(n)) if n else "  - "
        note = "" if n >= args.min_looks else "   (fewer than {} looks: left out)".format(args.min_looks)
        print("{:4.1f} - {:4.1f}  | {:5d} | {:5d} |   {}    | {:.2f} - {:.2f}{}".format(lower, upper, n, k, rate, lo, hi, note))
        lower = upper
    rows = table_rows(counts, args.min_looks)
    if rows:
        print("\nfor robot/config/<mode>.yaml:")
        print("d_by_range: [{}]".format(", ".join("[{}, {}]".format(u, v) for u, v in rows)))
    else:
        print("\nno bin has {} looks: nothing to put into the config".format(args.min_looks))

    if args.compare:
        base = Params.load(args.config)
        table = rows or base.d_by_range
        if not table:
            print("\n--compare needs a table: none fitted and none in the config")
            return 1
        flat = Params.load(args.config)
        flat.d_by_range = []
        ranged = Params.load(args.config)
        ranged.d_by_range = table
        print("\nreplay (p_update_dist {} m, f {}, tau {} s): d = {} everywhere / the table".format(
            base.p_update_dist, base.f, base.tau, base.d))
        for path, run in runs:
            a, b = replay(run, flat), replay(run, ranged)
            print("  {}".format(path))
            print("  id label        looks found counted | lowest p   final p  | lowest p   final p")
            for i in sorted(a):
                if not wanted({"id": i, "label": a[i]["label"]}, labels, ids):
                    continue
                print("  #{:<3d} {:<12s} {:5d} {:5d} {:7d} |   {:.2f}      {:.2f}    |   {:.2f}      {:.2f}".format(
                    i, a[i]["label"] or "-", a[i]["looks"], a[i]["hits"], a[i]["counted"],
                    a[i]["min"], a[i]["p"], b[i]["min"], b[i]["p"]))

    if args.write_config:
        problem = table_problem(rows)
        if problem:
            print("\nNOT written to {}: {}".format(args.write_config, problem))
            return 2
        note = "measured {} from {} looks ({})".format(
            time.strftime("%Y-%m-%d"), total, ", ".join(labels + ["#%d" % i for i in ids]) or "every memory")
        write_config(args.write_config, rows, note)
        print("\nwritten to {}: used from the next start of the observer".format(args.write_config))
    return 0


if __name__ == "__main__":
    sys.exit(main())
