"""Evaluation for the report (proposal section 7), in the toy world or on a real run.

Success of one query (both top-1 and top-3): the re-check passes AND the found
memory's position is within `radius` (0.5 m) of the target's true position.
top-1 = success on the first visit; top-3 = success within the top_k (3) visits.
Position error = distance from the top-1 candidate's position to the truth.
"""
import math
import os
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

from objmem.sim.baseline import LabelQueryMemory
from objmem.sim.runner import Sim, distance
from objmem.sim.sensors import query_label
from objmem.sim.world import MOVE_SPOTS

RADIUS = 0.5


# ---------------------------------------------------------------- counting
class Tally:
    def __init__(self):
        self.n = 0
        self.top1 = 0
        self.top3 = 0
        self.visits = 0
        self.errors: List[float] = []

    def add(self, top1: bool, top3: bool, visits: int, err: float) -> None:
        self.n += 1
        self.top1 += int(top1)
        self.top3 += int(top3)
        self.visits += visits
        if math.isfinite(err):
            self.errors.append(err)

    @staticmethod
    def pct(k: int, n: int) -> str:
        return "{:.1f}% ({}/{})".format(100.0 * k / n, k, n) if n else "-"

    def err_mean(self) -> str:
        return "{:.3f}".format(float(np.mean(self.errors))) if self.errors else "-"

    def err_median(self) -> str:
        return "{:.3f}".format(float(np.median(self.errors))) if self.errors else "-"

    def mean_visits(self) -> str:
        return "{:.2f}".format(self.visits / self.n) if self.n else "-"


def judge(result, truth_xy: Tuple[float, float], radius: float = RADIUS) -> Tuple[bool, bool]:
    ok = result.status == "found" and distance(result.item, truth_xy) <= radius
    top1 = ok and len(result.tried) >= 1 and result.tried[0][1] == "found"
    return top1, ok


def _run_queries(sim: Sim, queries: Sequence[Dict[str, str]], tally: Tally, label_search: bool = False,
                 per_object: Optional[Dict[str, List[float]]] = None,
                 subset: Optional[Sequence[str]] = None, tally_subset: Optional[Tally] = None) -> None:
    snap = sim.snapshot()
    seen_targets = set()
    for q in queries:
        sim.restore(snap)
        text, target = q["text"], q["target"]
        o = sim.world.object(target)
        truth = (o.x, o.y)
        emb = sim.embedder.embed_text(text)
        mem = LabelQueryMemory(sim.memory, query_label(text)) if label_search else sim.memory
        cands = mem.query(emb, sim.world.t)
        err = distance(cands[0].item, truth) if cands else float("inf")
        result = sim.ask(text, label_search=label_search)
        top1, top3 = judge(result, truth)
        tally.add(top1, top3, len(result.tried), err)
        if tally_subset is not None and subset is not None and target in subset:
            tally_subset.add(top1, top3, len(result.tried), err)
        if per_object is not None and target not in seen_targets:
            seen_targets.add(target)
            per_object.setdefault(target, []).append(err)
    sim.restore(snap)


# ---------------------------------------------------------------- toy-world experiments
def static_search(mode: str, seeds: Sequence[int], queries, label_search: bool = False,
                  per_object: Optional[Dict[str, List[float]]] = None, memory: str = "prob"):
    """Patrol once, then run every query from the same memory."""
    tally = Tally()
    n_items = []
    for seed in seeds:
        sim = Sim(mode=mode, seed=seed, memory=memory)
        sim.patrol()
        n_items.append(len(sim.memory.items))
        _run_queries(sim, queries, tally, label_search=label_search, per_object=per_object)
    return tally, float(np.mean(n_items))


def moved_search(mode: str, seeds: Sequence[int], queries, memory: str = "prob",
                 moves: Optional[Dict[str, Tuple[float, float]]] = None):
    """Patrol, move objects, patrol again, then run every query."""
    moves = MOVE_SPOTS if moves is None else moves
    all_t, moved_t = Tally(), Tally()
    for seed in seeds:
        sim = Sim(mode=mode, seed=seed, memory=memory)
        sim.patrol()
        for name, (x, y) in sorted(moves.items()):
            sim.world.move(name, x, y)
        sim.patrol()
        _run_queries(sim, queries, all_t, subset=list(moves), tally_subset=moved_t)
    return moved_t, all_t


def table(header: Sequence[str], rows: Sequence[Sequence[str]]) -> str:
    out = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return "\n".join(out)


def evaluate_toy(seeds: Sequence[int], queries, out_dir: Optional[str] = None, log=print) -> Dict[str, str]:
    """All toy-world tables. Returns {name: markdown}; also prints them with `log`."""
    tables = {}
    modes = ("depth", "nodepth")

    rows, per_obj = [], {m: {} for m in modes}
    for mode in modes:
        for label_search in (False, True):
            tally, n_items = static_search(mode, seeds, queries, label_search=label_search,
                                           per_object=per_obj[mode] if not label_search else None)
            rows.append([mode, "label match" if label_search else "CLIP", Tally.pct(tally.top1, tally.n),
                         Tally.pct(tally.top3, tally.n), tally.err_mean(), tally.err_median(),
                         tally.mean_visits(), "{:.1f}".format(n_items)])
    tables["search"] = table(["camera", "search", "top-1 success", "top-3 success", "pos. error mean (m)",
                              "pos. error median (m)", "visits / query", "memories (10 objects)"], rows)

    rows = []
    for mode in modes:
        for memory in ("prob", "baseline"):
            moved_t, all_t = moved_search(mode, seeds, queries, memory=memory)
            rows.append([mode, "probabilistic" if memory == "prob" else "baseline (append, similarity only)",
                         Tally.pct(moved_t.top1, moved_t.n), Tally.pct(moved_t.top3, moved_t.n),
                         moved_t.mean_visits(), Tally.pct(all_t.top1, all_t.n), Tally.pct(all_t.top3, all_t.n)])
    tables["moved"] = table(["camera", "memory", "moved: top-1", "moved: top-3", "moved: visits / query",
                             "all: top-1", "all: top-3"], rows)

    names = sorted(set(per_obj["depth"]) | set(per_obj["nodepth"]))
    rows = []
    for n in names:
        cells = [n]
        for mode in modes:
            e = [x for x in per_obj[mode].get(n, []) if math.isfinite(x)]
            cells.append("{:.3f}".format(float(np.mean(e))) if e else "-")
        rows.append(cells)
    tables["position"] = table(["object", "depth: error (m)", "nodepth: error (m)"], rows)

    if out_dir:
        from objmem.viz import save_map
        for mode in modes:
            sim = Sim(mode=mode, seed=seeds[0])
            sim.patrol()
            path = os.path.join(out_dir, "eval_map_{}.png".format(mode))
            save_map(path, sim.memory.items, occupancy=sim.world.occupancy(), truth=sim.world.truth(),
                     path=sim.world.trail, title="toy world, {} camera, seed {}: memory after one patrol".format(
                         mode, seeds[0]))
            tables["figure_" + mode] = path
    return tables


# ---------------------------------------------------------------- real runs
def load_ground_truth(path: str):
    import yaml
    with open(path, "r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    objects = {}
    for name, v in (data.get("objects") or {}).items():
        if v and v.get("x") is not None and v.get("y") is not None:
            objects[name] = (float(v["x"]), float(v["y"]))
    moved = sorted(data.get("moved") or [], key=lambda m: float(m["t"]))
    return objects, moved


def truth_at(objects, moved, name: str, t: float) -> Optional[Tuple[float, float]]:
    xy = objects.get(name)
    for m in moved:
        if m["object"] == name and float(m["t"]) <= t:
            xy = (float(m["x"]), float(m["y"]))
    return xy


def _norm(text: str) -> str:
    return " ".join("".join(c.lower() if c.isalnum() else " " for c in text).split())


def evaluate_real(memory_path: str, log_path: str, gt_path: str, queries, params=None,
                  map_yaml: Optional[str] = None, out_dir: Optional[str] = None, log=print) -> Dict[str, str]:
    """Score a real run: a saved memory file plus the JSON-lines search log of objmem.search.find."""
    from objmem.memory import ObjectMemory
    from objmem.search import read_log

    memory = ObjectMemory.load(memory_path, params)
    records = read_log(log_path)
    objects, moved = load_ground_truth(gt_path)
    targets = {_norm(q["text"]): q["target"] for q in queries}
    tally = Tally()
    rows, skipped = [], []
    for rec in records:
        text = rec.get("query", "")
        target = rec.get("target") or targets.get(_norm(text))
        truth = truth_at(objects, moved, target, float(rec.get("t_start", 0.0))) if target else None
        if truth is None:
            skipped.append(text)
            continue
        cands = {c["id"]: c for c in rec.get("candidates", [])}
        first = rec.get("candidates", [None])[0] if rec.get("candidates") else None
        err = math.hypot(first["mu"][0] - truth[0], first["mu"][1] - truth[1]) if first else float("inf")
        visits = rec.get("visits", [])
        found_id = rec.get("found_id")
        ok = False
        if rec.get("status") == "found" and found_id in cands:
            mu = cands[found_id]["mu"]
            ok = math.hypot(mu[0] - truth[0], mu[1] - truth[1]) <= RADIUS
        top1 = ok and bool(visits) and visits[0].get("outcome") == "found"
        tally.add(top1, ok, len(visits), err)
        dur = float(rec.get("t_end", 0.0)) - float(rec.get("t_start", 0.0))
        rows.append([text, target, rec.get("status"), "yes" if top1 else "no", "yes" if ok else "no",
                     "{:.2f}".format(err) if math.isfinite(err) else "-", str(len(visits)), "{:.1f}".format(dur)])
    tables = {}
    tables["queries"] = table(["query", "target", "status", "top-1", "top-3", "pos. error (m)", "visits",
                               "time (s)"], rows)
    tables["summary"] = table(["queries", "top-1 success", "top-3 success", "pos. error mean (m)",
                               "pos. error median (m)", "visits / query"],
                              [[str(tally.n), Tally.pct(tally.top1, tally.n), Tally.pct(tally.top3, tally.n),
                                tally.err_mean(), tally.err_median(), tally.mean_visits()]])
    mrows = []
    for it in sorted(memory.items, key=lambda i: -i.p):
        near, nd = "-", float("inf")
        for name, xy in objects.items():
            dd = math.hypot(float(it.mu[0]) - xy[0], float(it.mu[1]) - xy[1])
            if dd < nd:
                near, nd = name, dd
        mrows.append([str(it.id), str(it.label), "{:.2f}".format(float(it.mu[0])), "{:.2f}".format(float(it.mu[1])),
                      "{:.2f}".format(it.p), str(it.n_obs), near, "{:.2f}".format(nd) if math.isfinite(nd) else "-"])
    tables["memory"] = table(["id", "label", "x", "y", "p", "n_obs", "nearest object", "distance (m)"], mrows)
    if skipped:
        tables["skipped"] = "Skipped (no target or no ground truth): " + "; ".join(skipped)
    if out_dir:
        from objmem.viz import save_map
        path = os.path.join(out_dir, "real_map.png")
        save_map(path, memory.items, occupancy=map_yaml, truth=objects, title="real run: " + memory_path)
        tables["figure"] = path
    return tables
