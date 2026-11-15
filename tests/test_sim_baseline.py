import numpy as np

from objmem.sim.baseline import BaselineMemory, LabelQueryMemory
from objmem.types import Observation, Params, Pose2D


def _unit(v):
    v = np.asarray(v, dtype=np.float32)
    return v / np.linalg.norm(v)


def _obs(e, x, y, label="cup", t=0.0):
    return Observation(embedding=_unit(e), mu=np.array([x, y]), cov=np.eye(2) * 0.01, t=t,
                       view_pose=Pose2D(x - 1.0, y, 0.0), label=label)


def test_baseline_appends_every_observation_and_ranks_by_similarity():
    rng = np.random.default_rng(0)
    a, b = rng.standard_normal(512), rng.standard_normal(512)
    m = BaselineMemory(Params())
    m.update_frame([_obs(a, 1, 1), _obs(b, 2, 2, label="book")], Pose2D(0, 0, 0), lambda mu, p: True, 0.0)
    m.update_frame([_obs(a, 1.01, 1.0)], Pose2D(0, 0, 0), lambda mu, p: True, 1.0)  # no fusion
    assert len(m.items) == 3
    assert all(it.p == 1.0 for it in m.items)
    c = m.query(_unit(a), 2.0)
    assert [x.item.id for x in c][:2] in ([0, 2], [2, 0])
    assert c[0].sim > c[2].sim
    m.mark_not_found(0, 3.0)
    assert m.items[0].p == 1.0  # no confidence
    assert m.query(_unit(a), 2.0, k=1)[0].item.id in (0, 2)


def test_baseline_save_load_roundtrip(tmp_path):
    rng = np.random.default_rng(1)
    m = BaselineMemory()
    m.update_frame([_obs(rng.standard_normal(512), 1, 2, label=None, t=5.0)], Pose2D(0, 0, 0), lambda mu, p: True, 5.0)
    path = str(tmp_path / "b.npz")
    m.save(path)
    m2 = BaselineMemory.load(path)
    assert len(m2.items) == 1
    assert np.allclose(m2.items[0].mu, [1, 2])
    assert m2.items[0].label is None
    assert m2.items[0].t_last == 5.0


def test_empty_baseline_query():
    assert BaselineMemory().query(_unit(np.ones(512)), 0.0) == []


def test_label_query_memory_filters_by_label_and_ranks_by_p():
    rng = np.random.default_rng(2)
    m = BaselineMemory()
    m.update_frame([_obs(rng.standard_normal(512), 1, 1, "cup"), _obs(rng.standard_normal(512), 2, 2, "book"),
                    _obs(rng.standard_normal(512), 3, 3, "cup")], Pose2D(0, 0, 0), lambda mu, p: True, 0.0)
    m.items[2].p = 1.0
    m.items[0].p = 0.5
    lq = LabelQueryMemory(m, "cup")
    c = lq.query(np.zeros(512), 0.0)
    assert [x.item.id for x in c] == [2, 0]
    assert LabelQueryMemory(m, None).query(np.zeros(512), 0.0) == []
    assert LabelQueryMemory(m, "laptop").query(np.zeros(512), 0.0) == []
