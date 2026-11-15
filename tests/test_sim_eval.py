import json
import os
import subprocess
import sys

import numpy as np
import pytest

from objmem.memory import ObjectMemory
from objmem.sim.demo import run_demo
from objmem.sim.evaluation import evaluate_real, evaluate_toy, judge, truth_at
from objmem.sim.runner import Sim, clone_memory, load_queries
from objmem.types import Observation, Params, Pose2D, SearchResult

ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))


def test_queries_file_has_20_known_targets():
    qs = load_queries(os.path.join(ROOT, "data", "queries.yaml"))
    assert len(qs) == 20
    from objmem.sim.world import ToyWorld
    names = set(ToyWorld().objects)
    assert {q["target"] for q in qs} <= names
    import yaml
    gt = yaml.safe_load(open(os.path.join(ROOT, "data", "ground_truth.yaml"), encoding="utf-8"))
    assert set(gt["objects"]) == names


@pytest.mark.parametrize("mode", ["depth", "nodepth"])
def test_demo_story(mode):
    lines = []
    s = run_demo(mode, seed=2, say=lines.append)
    text = "\n".join(lines)
    assert s["first"][0] == "found" and s["first"][2] < 0.5
    assert s["old_failed"], text                     # old place fails
    assert s["p_old"][1] < s["p_old"][0]             # its confidence drops
    assert s["second"][0] == "found" and s["second"][2] < 0.5  # new place succeeds
    assert s["p_old_final"] < 0.3
    assert "old place failed the re-check" in text and "new place succeeded" in text


def test_demo_is_deterministic():
    a, b = [], []
    run_demo("nodepth", seed=1, say=a.append)
    run_demo("nodepth", seed=1, say=b.append)
    assert a == b


def test_clone_memory_is_independent():
    sim = Sim(seed=0)
    sim.patrol()
    c = clone_memory(sim.memory, sim.params)
    i0 = c.items[0].id
    c.mark_not_found(i0, sim.world.t)
    assert c.get(i0).p < sim.memory.get(i0).p


def test_judge():
    from objmem.types import MemoryItem
    it = MemoryItem(id=1, mu=np.array([1.0, 1.0]), cov=np.eye(2), embedding=np.zeros(512), p=0.9, t_last=0,
                    n_obs=1, view_pose=Pose2D(0, 0, 0))
    assert judge(SearchResult("found", it, [(1, "found")]), (1.2, 1.0)) == (True, True)
    assert judge(SearchResult("found", it, [(0, "not_found"), (1, "found")]), (1.2, 1.0)) == (False, True)
    assert judge(SearchResult("found", it, [(1, "found")]), (2.0, 1.0)) == (False, False)
    assert judge(SearchResult("not_found", None, [(1, "not_found")]), (1.0, 1.0)) == (False, False)


def test_evaluate_toy_small(tmp_path):
    qs = load_queries(os.path.join(ROOT, "data", "queries.yaml"))[:4]
    t1 = evaluate_toy([0], qs, out_dir=str(tmp_path), log=lambda *_: None)
    t2 = evaluate_toy([0], qs, out_dir=None, log=lambda *_: None)
    for k in ("search", "moved", "position"):
        assert t1[k] == t2[k]  # deterministic
        assert t1[k].startswith("| ")
    assert "label match" in t1["search"] and "baseline" in t1["moved"]
    assert os.path.exists(t1["figure_depth"]) and os.path.exists(t1["figure_nodepth"])


def test_probabilistic_memory_beats_baseline_after_moves():
    from objmem.sim.evaluation import moved_search
    qs = [q for q in load_queries(os.path.join(ROOT, "data", "queries.yaml"))
          if q["target"] in ("blue_mug", "red_mug", "green_tumbler", "yellow_book")]
    prob, _ = moved_search("depth", [0, 1], qs, memory="prob")
    base, _ = moved_search("depth", [0, 1], qs, memory="baseline")
    assert prob.top1 > base.top1
    assert prob.top1 >= 0.9 * prob.n


def test_truth_at_follows_moves():
    objects = {"mug": (1.0, 1.0)}
    moved = [{"object": "mug", "t": 100, "x": 5.0, "y": 0.5}]
    assert truth_at(objects, moved, "mug", 50) == (1.0, 1.0)
    assert truth_at(objects, moved, "mug", 150) == (5.0, 0.5)
    assert truth_at(objects, moved, "cup", 150) is None


def _real_run(tmp_path):
    """A memory file and a search log as the ROS nodes would write them."""
    p = Params()
    m = ObjectMemory(p)
    e = np.zeros(512, dtype=np.float32)
    e[0] = 1.0
    ob = Observation(embedding=e, mu=np.array([1.0, 2.0]), cov=np.eye(2) * 0.01, t=10.0,
                     view_pose=Pose2D(0.0, 2.0, 0.0), label="cup")
    m.update_frame([ob], Pose2D(0.0, 2.0, 0.0), lambda mu, pose: True, 10.0)
    ob2 = Observation(embedding=-e, mu=np.array([3.0, 2.0]), cov=np.eye(2) * 0.01, t=10.0,
                      view_pose=Pose2D(2.0, 2.0, 0.0), label="cup")
    m.update_frame([ob2], Pose2D(2.0, 2.0, 0.0), lambda mu, pose: False, 11.0)
    mem = str(tmp_path / "memory.npz")
    m.save(mem)
    gt = tmp_path / "gt.yaml"
    gt.write_text("objects:\n  blue_mug: {x: 1.1, y: 2.0}\n  red_mug: {x: 3.0, y: 2.0}\n"
                  "  yellow_book: {x: null, y: null}\nmoved: []\n", encoding="utf-8")
    recs = [
        {"query": "Where is the blue mug?", "t_start": 20.0, "t_end": 40.0, "status": "found", "found_id": 0,
         "candidates": [{"id": 0, "label": "cup", "sim": 0.3, "p": 0.9, "score": 0.8, "mu": [1.0, 2.0]}],
         "visits": [{"id": 0, "outcome": "found", "goal": [0.4, 2.0, 0.0], "retried_view_pose": False,
                     "prob": 0.9, "error": None, "t_start": 21.0, "t_end": 39.0}]},
        {"query": "where is the RED mug", "t_start": 50.0, "t_end": 90.0, "status": "found", "found_id": 1,
         "candidates": [{"id": 0, "label": "cup", "sim": 0.3, "p": 0.9, "score": 0.5, "mu": [1.0, 2.0]},
                        {"id": 1, "label": "cup", "sim": 0.3, "p": 0.7, "score": 0.4, "mu": [3.0, 2.0]}],
         "visits": [{"id": 0, "outcome": "not_found"}, {"id": 1, "outcome": "found"}]},
        {"query": "Where is the yellow book?", "t_start": 95.0, "t_end": 96.0, "status": "empty",
         "found_id": None, "candidates": [], "visits": []},
        {"query": "something else", "t_start": 97.0, "t_end": 98.0, "status": "empty", "found_id": None,
         "candidates": [], "visits": []},
    ]
    log = tmp_path / "search_log.jsonl"
    log.write_text("".join(json.dumps(r) + "\n" for r in recs), encoding="utf-8")
    return mem, str(log), str(gt)


def test_evaluate_real_run(tmp_path):
    mem, log, gt = _real_run(tmp_path)
    qs = load_queries(os.path.join(ROOT, "data", "queries.yaml"))
    t = evaluate_real(mem, log, gt, qs, out_dir=str(tmp_path), log=lambda *_: None)
    assert "| 2 | 50.0% (1/2) | 100.0% (2/2) |" in t["summary"]
    assert "blue_mug" in t["queries"] and "red_mug" in t["queries"]
    assert "Where is the yellow book?" in t["skipped"] and "something else" in t["skipped"]
    assert os.path.exists(t["figure"])
    assert t["memory"].count("\n") == 3  # header, rule, two items


def test_scripts_run(tmp_path):
    env = dict(os.environ)
    env["PYTHONPATH"] = os.path.join(ROOT, "src")
    out = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "demo_offline.py"), "--camera", "nodepth"],
                         capture_output=True, text=True, env=env, timeout=120)
    assert out.returncode == 0, out.stderr
    assert "new place succeeded" in out.stdout
    mem, log, gt = _real_run(tmp_path)
    out = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "evaluate.py"), "--memory", mem,
                          "--log", log, "--ground-truth", gt, "--out-dir", str(tmp_path / "o")],
                         capture_output=True, text=True, env=env, timeout=120)
    assert out.returncode == 0, out.stderr
    assert "Real run: summary" in out.stdout
