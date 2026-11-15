"""objmem.search against the real ObjectMemory (lane/1-memory)."""
import math

import numpy as np
import pytest

from objmem.memory import ObjectMemory, bayes_negative, bayes_positive
from objmem.search import find, goal_for, read_log
from objmem.types import Observation, Params, Pose2D

T0 = 1000.0


def vec(a, b=0.0, c=0.0):
    """Unit vector in the first three of 512 dimensions."""
    v = np.zeros(512, dtype=np.float32)
    v[0], v[1], v[2] = a, b, c
    return v / np.linalg.norm(v)


MUG = vec(1.0, 0.0, 0.0)
MUG_LIKE = vec(0.9, 0.436, 0.0)   # looks a bit like a mug
BOOK = vec(0.0, 0.0, 1.0)


class TextEmbedder:
    def __init__(self, table):
        self.table = table

    def embed_images(self, images):
        return np.zeros((len(images), 512), dtype=np.float32)

    def embed_text(self, text):
        return self.table[text]


class Nav:
    def __init__(self, results=()):
        self.results = list(results)
        self.goals = []

    def go_to(self, pose):
        self.goals.append(pose)
        return self.results.pop(0) if self.results else True


class Check:
    def __init__(self, results):
        self.results = list(results)

    def check(self, text):
        return self.results.pop(0)


def clock_from(start):
    state = {"t": start}

    def clock():
        state["t"] += 1.0
        return state["t"]

    return clock


def obs(embedding, mu, view, label, cov=0.01):
    return Observation(embedding=embedding, mu=np.array(mu, dtype=float), cov=np.eye(2) * cov,
                       t=T0, view_pose=Pose2D(*view), label=label)


@pytest.fixture
def params():
    return Params()


@pytest.fixture
def memory(params):
    mem = ObjectMemory(params)
    mem.update_frame(
        [
            obs(MUG, (2.0, 0.0), (0.0, 0.0, 0.0), "mug"),
            obs(MUG_LIKE, (0.0, 3.0), (0.0, 1.0, math.pi / 2), "cup"),
            obs(BOOK, (-2.0, -2.0), (-1.0, -1.0, -2.3), "book"),
        ],
        Pose2D(0.0, 0.0, 0.0), lambda mu, pose: False, T0)
    return mem


@pytest.fixture
def embedder():
    return TextEmbedder({"the mug": MUG})


def test_found_at_best_candidate_raises_confidence(memory, embedder, params):
    mug = memory.items[0]
    nav = Nav()
    result = find("the mug", memory, embedder, nav, Check([(True, 0.9)]), params, clock=clock_from(T0))

    assert result.status == "found"
    assert result.item is mug
    assert result.tried == [(mug.id, "found")]
    assert nav.goals[0].x == pytest.approx(2.0 - params.standoff)
    assert nav.goals[0].yaw == pytest.approx(0.0)
    # A few seconds of decay are negligible against tau = 600 s.
    assert mug.p == pytest.approx(bayes_positive(params.p_init, params.d, params.f), abs=2e-3)
    assert mug.p > params.p_init


def test_moved_object_old_place_fails_then_next_candidate_found(memory, embedder, params, tmp_path):
    mug, cup, book = memory.items
    log = str(tmp_path / "search.jsonl")
    nav = Nav()
    result = find("the mug", memory, embedder, nav, Check([(False, 0.1), (True, 0.8)]), params,
                  clock=clock_from(T0), log_path=log)

    assert result.status == "found"
    assert result.item is cup
    assert result.tried == [(mug.id, "not_found"), (cup.id, "found")]
    assert mug.p == pytest.approx(bayes_negative(params.p_init, params.d, params.f), abs=2e-3)
    assert mug.p < params.p_init < cup.p
    assert len(nav.goals) == 2
    goal = goal_for(cup, params)
    assert (nav.goals[1].x, nav.goals[1].y) == pytest.approx((goal.x, goal.y))

    record = read_log(log)[0]
    assert [c["id"] for c in record["candidates"]] == [mug.id, cup.id, book.id]
    assert record["candidates"][0]["p"] == pytest.approx(params.p_init, abs=2e-3)  # before the update
    assert record["candidates"][0]["mu"] == pytest.approx([2.0, 0.0])
    assert record["candidates"][0]["score"] > record["candidates"][1]["score"]
    assert [v["outcome"] for v in record["visits"]] == ["not_found", "found"]
    assert record["found_id"] == cup.id


def test_failed_search_changes_the_next_ranking(memory, embedder, params):
    mug, cup, book = memory.items
    # Nothing is found anywhere: every candidate loses confidence.
    result = find("the mug", memory, embedder, Nav(), Check([(False, 0.1)] * 3), params, clock=clock_from(T0))
    assert result.status == "not_found"
    assert [i for i, _ in result.tried] == [mug.id, cup.id, book.id]
    assert all(item.p < params.p_init for item in memory.items)

    # The mug is then seen again at the cup's place; the old mug memory stays low.
    result = find("the mug", memory, embedder, Nav(), Check([(False, 0.1), (True, 0.9)]), params,
                  clock=clock_from(T0 + 10))
    assert result.status == "found"
    assert result.item is cup
    assert cup.p > mug.p


def test_nav_failure_leaves_confidence_alone(memory, embedder, params):
    mug, cup, _ = memory.items
    nav = Nav([False, False, True])
    result = find("the mug", memory, embedder, nav, Check([(True, 0.9)]), params, clock=clock_from(T0))
    assert result.tried == [(mug.id, "nav_failed"), (cup.id, "found")]
    assert mug.p == pytest.approx(params.p_init, abs=2e-3)
    # First goal, then the view_pose retry.
    assert (nav.goals[1].x, nav.goals[1].y, nav.goals[1].yaw) == (0.0, 0.0, 0.0)


def test_empty_real_memory(embedder, params):
    result = find("the mug", ObjectMemory(params), embedder, Nav(), Check([]), params)
    assert result.status == "empty"
    assert result.tried == []


def test_top_k_limits_the_visits(memory, embedder, params):
    params.top_k = 2
    nav = Nav()
    result = find("the mug", memory, embedder, nav, Check([(False, 0.1)] * 3), params, clock=clock_from(T0))
    assert len(result.tried) == 2
    assert len(nav.goals) == 2


def test_nodepth_first_sighting_goes_to_view_pose(embedder, params):
    # A single nodepth sighting has a long covariance along the ray.
    mem = ObjectMemory(params)
    cov = np.diag([params.sigma_range_nodepth ** 2, (params.nominal_range * params.sigma_bearing) ** 2])
    view = (0.5, 0.2, 0.0)
    mem.update_frame(
        [Observation(embedding=MUG, mu=np.array([2.5, 0.2]), cov=cov, t=T0, view_pose=Pose2D(*view),
                     label="mug", bearing=0.0)],
        Pose2D(*view), lambda mu, pose: False, T0)
    nav = Nav()
    result = find("the mug", mem, embedder, nav, Check([(True, 0.9)]), params, clock=clock_from(T0))
    assert result.status == "found"
    assert (nav.goals[0].x, nav.goals[0].y, nav.goals[0].yaw) == view
