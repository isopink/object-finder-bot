"""scripts/fit_detection_range.py on a log written by the real memory."""
import json
import os
import sys

import numpy as np
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import fit_detection_range as fit  # noqa: E402
from objmem.memory import ObjectMemory, bayes_negative, bayes_positive, detect_prob  # noqa: E402
from objmem.types import Observation, Params, Pose2D  # noqa: E402

COV = [[0.0025, 0.0], [0.0, 0.0025]]


def unit(k):
    v = np.zeros(512, dtype=np.float32)
    v[k] = 1.0
    return v


def look(mem, x, found, t):
    """The robot at (x, 0) facing +x looks at the cup at (4, 0)."""
    obs = [Observation(embedding=unit(0), mu=np.array([4.0, 0.0]), cov=np.array(COV), t=t,
                       view_pose=Pose2D(x, 0.0, 0.0), label="cup")] if found else []
    mem.update_frame(obs, Pose2D(x, 0.0, 0.0), lambda mu, pose: True, t)


def test_detect_prob_table_and_floor():
    p = Params(d=0.8, f=0.1, d_by_range=[[2.0, 0.9], [3.0, 0.5], [4.0, 0.05]])
    assert [detect_prob(r, p) for r in (0.5, 2.0, 2.5, 3.5, 9.0)] == [0.9, 0.9, 0.5, 0.1, 0.1]   # never below f
    assert detect_prob(3.0, Params(d=0.8)) == 0.8


def test_memory_uses_the_distance_of_the_look():
    """Missing the cup from 3.4 m (table: 0.3) lowers p less than from 0.9 m (0.9)."""
    table = [[1.0, 0.9], [4.0, 0.3]]
    for x, d in ((0.55, 0.3), (3.05, 0.9)):                 # camera 5 cm ahead of the robot
        mem = ObjectMemory(Params(d_by_range=table, cam_x=0.05, tau=1e12))
        look(mem, x, True, 0.0)
        look(mem, x, False, 1.0)
        assert mem.items[0].p == pytest.approx(bayes_negative(0.7, d, 0.1))
        look(mem, x, True, 2.0)
        assert mem.items[0].p == pytest.approx(bayes_positive(bayes_negative(0.7, d, 0.1), d, 0.1))


def test_evidence_log_fit_and_replay(tmp_path, capsys):
    path = str(tmp_path / "logs" / "evidence.jsonl")
    params = Params(evidence_log=path, cam_x=0.0, tau=1e12)
    mem = ObjectMemory(params)
    look(mem, 3.5, True, 0.0)                                # the look that makes the memory: not counted
    t = 1.0
    for x, found in [(0.5, True)] * 3 + [(0.5, False)] + [(2.5, True)] * 6 + [(2.5, False)] * 2:
        look(mem, x, found, t)                               # 3.5 m: 3 of 4, 1.5 m: 6 of 8
        t += 1.0
    frames = fit.read_log(path)
    assert len(frames) == 13 and frames[0]["items"][0].get("new") == 1
    assert frames[1]["items"][0] == {"id": 0, "label": "cup", "r": 3.5, "hit": 1, "counted": 1,
                                     "p": round(bayes_positive(0.7, 0.8, 0.1), 4)}
    counts = fit.count(frames, [1.0, 2.0, 3.0, 4.0], labels=["cup"])
    assert counts == [(1.0, 0, 0), (2.0, 8, 6), (3.0, 0, 0), (4.0, 4, 3)]
    assert fit.count(frames, [4.0], labels=["laptop"]) == [(4.0, 0, 0)]
    assert fit.table_rows(counts, min_looks=4) == [[2.0, 0.75], [4.0, 0.75]]
    assert fit.table_rows([(1.0, 10, 10), (2.0, 10, 0)], 5) == [[1.0, 0.98], [2.0, 0.02]]

    # the replay with the values of the run gives the p of the run
    assert fit.replay(frames, Params(cam_x=0.0, tau=1e12))[0]["p"] == pytest.approx(mem.items[0].p, abs=1e-9)
    weak = fit.replay(frames, Params(cam_x=0.0, tau=1e12, d_by_range=[[4.0, 0.2]]))[0]
    assert weak["looks"] == 12 and weak["hits"] == 9
    assert 0.7 < weak["p"] < mem.items[0].p                  # the same looks, weaker evidence

    assert fit.main([path, "--label", "cup", "--edges", "2,4", "--min-looks", "4", "--compare"]) == 0
    out = capsys.readouterr().out
    assert "d_by_range: [[2.0, 0.75], [4.0, 0.75]]" in out and "replay" in out


def test_wilson_interval():
    lo, hi = fit.wilson(8, 10)
    assert 0.48 < lo < 0.50 and 0.94 < hi < 0.95
    assert fit.wilson(0, 0) == (0.0, 1.0)


def test_a_log_that_cannot_be_written_does_not_stop_the_memory(tmp_path, capsys):
    blocker = tmp_path / "file"
    blocker.write_text("x", encoding="utf-8")
    mem = ObjectMemory(Params(evidence_log=str(blocker / "evidence.jsonl")))
    look(mem, 3.5, True, 0.0)
    look(mem, 3.5, True, 1.0)
    assert len(mem.items) == 1 and capsys.readouterr().out.count("cannot write the evidence log") == 1
