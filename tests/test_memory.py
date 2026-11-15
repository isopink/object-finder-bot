"""Tests for objmem.memory with hand-computed numbers."""
import math

import numpy as np
import pytest

from objmem.memory import (ObjectMemory, bayes_negative, bayes_positive, bearing_update,
                           kalman_update, time_decay)
from objmem.types import Observation, Params, Pose2D

DIM = 512


def unit(k, dim=DIM):
    v = np.zeros(dim, dtype=np.float32)
    v[k] = 1.0
    return v


def mix(a, b, w):
    v = (1 - w) * a + w * b
    return (v / np.linalg.norm(v)).astype(np.float32)


def obs(mu, cov, emb, t=0.0, pose=None, label=None, bearing=None):
    return Observation(embedding=emb, mu=np.array(mu, dtype=float), cov=np.array(cov, dtype=float),
                       t=t, view_pose=pose or Pose2D(0.0, 0.0, 0.0), label=label, bearing=bearing)


def never(mu, pose):
    return False


def always(mu, pose):
    return True


def ray_gaussian(pose, bearing, params):
    """Local stand-in for objmem.bearing.ray_gaussian (Session 2), as the brief defines it."""
    u = np.array([math.cos(bearing), math.sin(bearing)])
    n = np.array([-u[1], u[0]])
    mu = np.array([pose.x, pose.y]) + params.nominal_range * u
    s_along = params.sigma_range_nodepth
    s_across = params.nominal_range * params.sigma_bearing
    cov = s_along ** 2 * np.outer(u, u) + s_across ** 2 * np.outer(n, n)
    return mu, cov


def nodepth_obs(target, pose, params, emb, t):
    b = math.atan2(target[1] - pose.y, target[0] - pose.x)
    mu, cov = ray_gaussian(pose, b, params)
    return obs(mu, cov, emb, t=t, pose=pose, bearing=b)


I = np.eye(2)


# ---------------------------------------------------------------- formulas
def test_kalman_update_hand_computed():
    mu, cov = kalman_update(np.zeros(2), 0.04 * I, np.array([0.1, 0.0]), 0.04 * I)
    assert np.allclose(mu, [0.05, 0.0])
    assert np.allclose(cov, 0.02 * I)


def test_kalman_update_unequal_noise():
    # K = 0.01 / (0.01 + 0.03) = 0.25 in x; 0.5 in y
    mu, cov = kalman_update(np.zeros(2), np.diag([0.01, 0.02]), np.array([0.4, 0.4]), np.diag([0.03, 0.02]))
    assert np.allclose(mu, [0.1, 0.2])
    assert np.allclose(cov, np.diag([0.0075, 0.01]))


def test_bearing_update_single_ekf_step():
    # H = [0, 1/1] at (1, 0); S = 0.01 + 0.01; K = (0, 0.5); innovation 0.1
    mu, cov = bearing_update(np.array([1.0, 0.0]), 0.01 * I, np.zeros(2), 0.1, 0.1, iters=1)
    assert np.allclose(mu, [1.0, 0.05])
    assert np.allclose(cov, np.diag([0.01, 0.005]))


def test_bearing_update_wraps_angle():
    # Estimate just below +pi, measurement just above -pi: innovation must be small.
    mu0 = np.array([-1.0, 0.01])
    mu, _ = bearing_update(mu0, 0.01 * I, np.zeros(2), -math.pi + 0.005, 0.1, iters=1)
    assert np.linalg.norm(mu - mu0) < 0.05


def test_bayes_positive_and_negative():
    assert bayes_positive(0.7, 0.8, 0.1) == pytest.approx(0.56 / 0.59)
    assert bayes_negative(0.7, 0.8, 0.1) == pytest.approx(0.14 / 0.41)


def test_time_decay_formula():
    assert time_decay(0.9, 600.0, 600.0) == pytest.approx(0.5 + 0.4 / math.e)
    assert time_decay(0.1, 600.0, 600.0) == pytest.approx(0.5 - 0.4 / math.e)
    assert time_decay(0.9, 0.0, 600.0) == 0.9
    assert time_decay(0.9, 1e9, 600.0) == pytest.approx(0.5)


# ---------------------------------------------------------------- update_frame
def test_new_memory_has_p_init_and_fields():
    pr = Params()
    mem = ObjectMemory(pr)
    pose = Pose2D(0.5, 0.0, 0.1)
    mem.update_frame([obs([1, 2], 0.01 * I, unit(0), t=5.0, pose=pose, label="mug")], pose, never, 5.0)
    (item,) = mem.items
    assert item.p == pytest.approx(pr.p_init)
    assert item.n_obs == 1 and item.t_last == 5.0 and item.label == "mug"
    assert np.allclose(item.mu, [1, 2])
    assert item.view_pose == pose


def test_matched_kalman_and_positive_bayes():
    pr = Params()
    mem = ObjectMemory(pr)
    pose = Pose2D(0, 0, 0)
    mem.update_frame([obs([0, 0], 0.04 * I, unit(0))], pose, never, 0.0)
    pose2 = Pose2D(1.0, 1.0, 0.5)
    mem.update_frame([obs([0.1, 0], 0.04 * I, unit(0), pose=pose2)], pose2, always, 0.0)
    (item,) = mem.items
    assert np.allclose(item.mu, [0.05, 0.0])
    assert np.allclose(item.cov, 0.02 * I)
    assert item.p == pytest.approx(0.56 / 0.59)
    assert item.n_obs == 2
    assert item.view_pose == pose2


def test_embedding_running_mean_renormalized():
    pr = Params(cos_thresh=0.5)
    mem = ObjectMemory(pr)
    e0, e1 = unit(0), mix(unit(0), unit(1), 0.3)
    mem.update_frame([obs([0, 0], 0.04 * I, e0)], Pose2D(0, 0, 0), never, 0.0)
    mem.update_frame([obs([0, 0], 0.04 * I, e1)], Pose2D(0, 0, 0), never, 0.0)
    expected = (e0 + e1) / np.linalg.norm(e0 + e1)
    assert np.allclose(mem.items[0].embedding, expected, atol=1e-6)
    assert np.linalg.norm(mem.items[0].embedding) == pytest.approx(1.0, abs=1e-6)


def test_negative_update_for_unmatched_in_view_only():
    pr = Params()
    mem = ObjectMemory(pr)
    mem.update_frame([obs([0, 0], 0.01 * I, unit(0)), obs([5, 5], 0.01 * I, unit(1))], Pose2D(0, 0, 0), never, 0.0)

    def near_origin(mu, pose):
        return float(np.linalg.norm(mu)) < 1.0

    mem.update_frame([], Pose2D(0, 0, 0), near_origin, 0.0)
    a, b = mem.items
    assert a.p == pytest.approx(0.14 / 0.41)
    assert b.p == pytest.approx(pr.p_init)


def test_new_memory_not_negatively_updated_in_same_frame():
    mem = ObjectMemory(Params())
    mem.update_frame([obs([0, 0], 0.01 * I, unit(0))], Pose2D(0, 0, 0), always, 0.0)
    assert mem.items[0].p == pytest.approx(0.7)


def test_gate_near_and_similar_matches():
    mem = ObjectMemory(Params())
    mem.update_frame([obs([1, 0], 0.01 * I, unit(0))], Pose2D(0, 0, 0), never, 0.0)
    mem.update_frame([obs([1.05, 0], 0.01 * I, mix(unit(0), unit(1), 0.1))], Pose2D(0, 0, 0), never, 0.0)
    assert len(mem) == 1 and mem.items[0].n_obs == 2


def test_gate_near_but_dissimilar_is_new():
    mem = ObjectMemory(Params())
    mem.update_frame([obs([1, 0], 0.01 * I, unit(0))], Pose2D(0, 0, 0), never, 0.0)
    mem.update_frame([obs([1.05, 0], 0.01 * I, unit(1))], Pose2D(0, 0, 0), never, 0.0)
    assert len(mem) == 2


def test_gate_far_but_similar_is_new():
    mem = ObjectMemory(Params())
    mem.update_frame([obs([1, 0], 0.01 * I, unit(0))], Pose2D(0, 0, 0), never, 0.0)
    # Mahalanobis = 2 / sqrt(0.02) = 14.1 > 3
    mem.update_frame([obs([3, 0], 0.01 * I, unit(0))], Pose2D(0, 0, 0), never, 0.0)
    assert len(mem) == 2


def test_one_to_one_association():
    mem = ObjectMemory(Params())
    mem.update_frame([obs([1, 0], 0.01 * I, unit(0))], Pose2D(0, 0, 0), never, 0.0)
    two = [obs([1.02, 0], 0.01 * I, unit(0)), obs([1.1, 0], 0.01 * I, unit(0))]
    mem.update_frame(two, Pose2D(0, 0, 0), never, 0.0)
    assert len(mem) == 2  # the closer one matched, the other became a new memory
    assert sorted(it.n_obs for it in mem.items) == [1, 2]
    assert np.allclose(mem.items[1].mu, [1.1, 0])


def test_ekf_bearing_converges_from_two_poses():
    pr = Params()
    mem = ObjectMemory(pr)
    target = (2.0, 1.0)
    pose_a, pose_b = Pose2D(0.0, 0.0, 0.46), Pose2D(3.0, -1.0, 2.0)
    mem.update_frame([nodepth_obs(target, pose_a, pr, unit(0), 0.0)], pose_a, never, 0.0)
    first = mem.items[0]
    assert np.linalg.norm(first.mu - np.array(target)) > 0.1  # ray guess at nominal range
    mem.update_frame([nodepth_obs(target, pose_b, pr, unit(0), 1.0)], pose_b, never, 1.0)
    (item,) = mem.items
    assert item.n_obs == 2
    assert np.linalg.norm(item.mu - np.array(target)) < 0.05
    assert np.linalg.eigvalsh(item.cov).max() < 0.01
    # More views keep it there and shrink the covariance further.
    before = np.linalg.eigvalsh(item.cov).max()
    for k, pose in enumerate([pose_a, pose_b, pose_a]):
        mem.update_frame([nodepth_obs(target, pose, pr, unit(0), 2.0 + k)], pose, never, 2.0 + k)
    item = mem.items[0]
    assert np.linalg.norm(item.mu - np.array(target)) < 0.02
    assert np.linalg.eigvalsh(item.cov).max() < before


def test_moved_object():
    pr = Params()
    mem = ObjectMemory(pr)
    old, new = np.array([1.0, 0.0]), np.array([3.0, 2.0])
    pose = Pose2D(0, 0, 0)
    mem.update_frame([obs(old, 0.01 * I, unit(0))], pose, never, 0.0)
    for _ in range(3):
        mem.update_frame([obs(old, 0.01 * I, unit(0))], pose, always, 0.0)
    old_item = mem.items[0]
    assert old_item.p > 0.99
    # The mug moves. The old place stays in view and is empty; the mug is seen at the new place.
    t = 1.0
    for _ in range(6):
        mem.update_frame([obs(new, 0.01 * I, unit(0))], pose, lambda mu, p: True, t)
        t += 1.0
    assert len(mem) == 2
    old_item, new_item = mem.items
    assert np.allclose(old_item.mu, old)
    assert old_item.p < 0.1
    assert new_item.p > 0.99
    cands = mem.query(unit(0), t)
    assert cands[0].item.id == new_item.id


# ---------------------------------------------------------------- decay
def test_decay_toward_half_and_no_double_decay():
    pr = Params(tau=600.0)
    mem = ObjectMemory(pr)
    mem.update_frame([obs([0, 0], 0.01 * I, unit(0))], Pose2D(0, 0, 0), never, 0.0)
    mem.mark_found(0, 0.0)  # p = 0.949...
    p0 = mem.items[0].p
    mem.decay_to(600.0)
    expected = 0.5 + (p0 - 0.5) / math.e
    assert mem.items[0].p == pytest.approx(expected)
    mem.decay_to(600.0)
    mem.query(unit(0), 600.0)
    mem.update_frame([], Pose2D(0, 0, 0), never, 600.0)
    assert mem.items[0].p == pytest.approx(expected)
    # Two steps equal one step over the whole interval.
    mem.decay_to(900.0)
    mem.decay_to(1200.0)
    assert mem.items[0].p == pytest.approx(0.5 + (p0 - 0.5) * math.exp(-2.0))
    # Going back in time does nothing.
    mem.decay_to(100.0)
    assert mem.items[0].p == pytest.approx(0.5 + (p0 - 0.5) * math.exp(-2.0))


def test_low_confidence_decays_up_toward_half():
    mem = ObjectMemory(Params(tau=100.0))
    mem.update_frame([obs([0, 0], 0.01 * I, unit(0))], Pose2D(0, 0, 0), never, 0.0)
    mem.mark_not_found(0, 0.0)
    p0 = mem.items[0].p
    assert p0 < 0.5
    mem.decay_to(1e6)
    assert mem.items[0].p == pytest.approx(0.5)


def test_decay_before_bayes_in_update_frame():
    pr = Params(tau=600.0)
    mem = ObjectMemory(pr)
    mem.update_frame([obs([0, 0], 0.01 * I, unit(0))], Pose2D(0, 0, 0), never, 0.0)
    mem.update_frame([obs([0, 0], 0.01 * I, unit(0))], Pose2D(0, 0, 0), never, 600.0)
    p_dec = 0.5 + 0.2 / math.e
    assert mem.items[0].p == pytest.approx(bayes_positive(p_dec, pr.d, pr.f))
    assert mem.items[0].t_last == 600.0


# ---------------------------------------------------------------- query and marks
def test_query_ranking_and_scores():
    pr = Params(T=0.05)
    mem = ObjectMemory(pr)
    e_q = unit(0)
    # two items with cosine 0.30 and 0.28 to the query
    ea = (0.30 * unit(0) + math.sqrt(1 - 0.30 ** 2) * unit(1)).astype(np.float32)
    eb = (0.28 * unit(0) + math.sqrt(1 - 0.28 ** 2) * unit(2)).astype(np.float32)
    ec = unit(3)
    mem.update_frame([obs([0, 0], 0.01 * I, ea), obs([5, 0], 0.01 * I, eb), obs([9, 0], 0.01 * I, ec)],
                     Pose2D(0, 0, 0), never, 0.0)
    mem.items[0].p = 0.3
    mem.items[1].p = 0.9
    mem.items[2].p = 0.9
    cands = mem.query(e_q, 0.0)
    assert [c.item.id for c in cands] == [1, 0, 2]
    z = np.array([0.30, 0.28, 0.0]) / 0.05
    w = np.exp(z) / np.exp(z).sum()
    assert cands[0].score == pytest.approx(w[1] * 0.9)
    assert cands[1].score == pytest.approx(w[0] * 0.3)
    assert cands[0].sim == pytest.approx(0.28, abs=1e-6)
    assert len(mem.query(e_q, 0.0, k=1)) == 1


def test_query_default_k_and_empty():
    mem = ObjectMemory(Params(top_k=2))
    assert mem.query(unit(0), 0.0) == []
    mem.update_frame([obs([i * 5.0, 0], 0.01 * I, unit(i)) for i in range(4)], Pose2D(0, 0, 0), never, 0.0)
    assert len(mem.query(unit(0), 0.0)) == 2
    assert mem.query(unit(0), 0.0)[0].item.id == 0


def test_mark_found_and_not_found():
    pr = Params()
    mem = ObjectMemory(pr)
    mem.update_frame([obs([0, 0], 0.01 * I, unit(0)), obs([5, 0], 0.01 * I, unit(1))],
                     Pose2D(0, 0, 0), never, 0.0)
    mem.mark_found(0, 0.0)
    mem.mark_not_found(1, 0.0)
    assert mem.items[0].p == pytest.approx(0.56 / 0.59)
    assert mem.items[1].p == pytest.approx(0.14 / 0.41)
    mem.mark_found(99, 0.0)  # unknown id is ignored
    mem.mark_not_found(99, 0.0)


# ---------------------------------------------------------------- save / load
def test_save_load_round_trip(tmp_path):
    pr = Params()
    mem = ObjectMemory(pr)
    mem.update_frame([obs([1, 2], np.array([[0.02, 0.01], [0.01, 0.03]]), unit(0), pose=Pose2D(0.1, 0.2, 0.3),
                          label="mug"),
                      obs([5, 0], 0.01 * I, unit(1), label=None)], Pose2D(0, 0, 0), never, 10.0)
    mem.mark_found(0, 50.0)
    mem.remove(1)
    mem.update_frame([obs([7, 7], 0.01 * I, unit(2), label="book")], Pose2D(0, 0, 0), never, 60.0)
    path = str(tmp_path / "sub" / "memory.npz")
    mem.save(path)
    back = ObjectMemory.load(path, pr)
    assert len(back) == len(mem) == 2
    for a, b in zip(mem.items, back.items):
        assert a.id == b.id and a.label == b.label and a.n_obs == b.n_obs
        assert np.array_equal(a.mu, b.mu) and np.array_equal(a.cov, b.cov)
        assert np.array_equal(a.embedding, b.embedding)
        assert a.p == b.p and a.t_last == b.t_last and a.view_pose == b.view_pose
    assert back._t_p == mem._t_p
    # New ids keep counting after the removed one.
    back.update_frame([obs([9, 9], 0.01 * I, unit(3))], Pose2D(0, 0, 0), never, 70.0)
    assert back.items[-1].id == 3
    # Decay after load matches decay before save.
    mem.decay_to(700.0)
    back.decay_to(700.0)
    assert back.items[0].p == pytest.approx(mem.items[0].p)


def test_save_load_empty(tmp_path):
    path = str(tmp_path / "empty.npz")
    ObjectMemory(Params()).save(path)
    back = ObjectMemory.load(path, Params())
    assert len(back) == 0 and back.items == []


def test_save_path_without_npz_suffix(tmp_path):
    mem = ObjectMemory(Params())
    mem.update_frame([obs([0, 0], 0.01 * I, unit(0))], Pose2D(0, 0, 0), never, 0.0)
    path = str(tmp_path / "memory.bin")
    mem.save(path)
    assert len(ObjectMemory.load(path)) == 1
