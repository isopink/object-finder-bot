"""Tests for objmem.search with fake memory, navigator, and verifier."""
import json
import math

import numpy as np
import pytest

from objmem.search import find, goal_for, read_log
from objmem.types import Candidate, MemoryItem, Params, Pose2D


# ------------------------------------------------------------------ fakes
def unit(index, dim=512):
    v = np.zeros(dim, dtype=np.float32)
    v[index] = 1.0
    return v


def make_item(item_id, mu=(2.0, 0.0), view=(0.0, 0.0, 0.0), cov=0.01, p=0.8, label=None):
    return MemoryItem(
        id=item_id,
        mu=np.array(mu, dtype=float),
        cov=np.eye(2) * cov,
        embedding=unit(item_id),
        p=p,
        t_last=0.0,
        n_obs=3,
        view_pose=Pose2D(*view),
        label=label,
    )


class FakeEmbedder:
    def __init__(self):
        self.texts = []

    def embed_images(self, images):
        return np.zeros((len(images), 512), dtype=np.float32)

    def embed_text(self, text):
        self.texts.append(text)
        return unit(0)


class FakeMemory:
    """Returns its items as candidates in the given order with falling scores."""

    def __init__(self, items):
        self._items = list(items)
        self.query_calls = []
        self.found = []
        self.not_found = []

    @property
    def items(self):
        return self._items

    def update_frame(self, observations, pose, in_view, t):
        raise AssertionError("search must not call update_frame")

    def query(self, text_embedding, t, k=None):
        self.query_calls.append((text_embedding, t, k))
        n = len(self._items)
        return [Candidate(item=it, sim=0.3 - 0.01 * i, score=(n - i) / float(n + 1))
                for i, it in enumerate(self._items)]

    def mark_found(self, item_id, t):
        self.found.append((item_id, t))

    def mark_not_found(self, item_id, t):
        self.not_found.append((item_id, t))

    def save(self, path):
        pass


class FakeNavigator:
    """Answers go_to calls from a list of results (True when the list runs out)."""

    def __init__(self, results=()):
        self.results = list(results)
        self.goals = []

    def go_to(self, pose):
        self.goals.append(pose)
        if self.results:
            result = self.results.pop(0)
            if isinstance(result, Exception):
                raise result
            return result
        return True


class FakeVerifier:
    def __init__(self, results=()):
        self.results = list(results)
        self.texts = []

    def check(self, text):
        self.texts.append(text)
        if self.results:
            result = self.results.pop(0)
            if isinstance(result, Exception):
                raise result
            return result
        return (False, 0.0)


class Clock:
    def __init__(self, start=1000.0, step=1.0):
        self.now = start
        self.step = step

    def __call__(self):
        value = self.now
        self.now += self.step
        return value


def same_pose(a, b, tol=1e-9):
    return abs(a.x - b.x) < tol and abs(a.y - b.y) < tol and abs(a.yaw - b.yaw) < tol


@pytest.fixture
def params():
    return Params()


# ------------------------------------------------------------------ goal_for
def test_goal_for_certain_position_is_standoff_point_facing_object(params):
    item = make_item(1, mu=(2.0, 0.0), view=(0.0, 0.0, 1.0))
    goal = goal_for(item, params)
    assert goal.x == pytest.approx(2.0 - params.standoff)
    assert goal.y == pytest.approx(0.0)
    assert goal.yaw == pytest.approx(0.0)


def test_goal_for_diagonal(params):
    # Object at (3, 4), seen from the origin: distance 5, unit vector (0.6, 0.8).
    item = make_item(1, mu=(3.0, 4.0), view=(0.0, 0.0, 0.0))
    goal = goal_for(item, params)
    assert goal.x == pytest.approx(3.0 - 0.6 * params.standoff)
    assert goal.y == pytest.approx(4.0 - 0.8 * params.standoff)
    assert goal.yaw == pytest.approx(math.atan2(4.0, 3.0))
    assert math.hypot(3.0 - goal.x, 4.0 - goal.y) == pytest.approx(params.standoff)


def test_goal_for_faces_object_from_the_view_side(params):
    # Seen from the +x side: the goal is on the +x side, facing -x.
    item = make_item(1, mu=(1.0, 1.0), view=(3.0, 1.0, math.pi))
    goal = goal_for(item, params)
    assert goal.x == pytest.approx(1.0 + params.standoff)
    assert goal.y == pytest.approx(1.0)
    assert abs(goal.yaw) == pytest.approx(math.pi)


def test_goal_for_uncertain_position_returns_view_pose(params):
    item = make_item(1, mu=(2.0, 0.0), view=(0.5, -0.5, 0.7))
    # Elongated covariance (nodepth first sighting): one large eigenvalue.
    item.cov = np.array([[2.25, 0.0], [0.0, 0.0036]])
    assert same_pose(goal_for(item, params), item.view_pose)
    # Rotated: the largest eigenvalue decides, not the diagonal entries.
    c, s = math.cos(0.8), math.sin(0.8)
    rot = np.array([[c, -s], [s, c]])
    item.cov = rot.dot(np.diag([0.3, 0.001])).dot(rot.T)
    assert same_pose(goal_for(item, params), item.view_pose)


def test_goal_for_threshold_is_pos_cov_max(params):
    item = make_item(1, mu=(2.0, 0.0), view=(0.0, 0.0, 0.3))
    item.cov = np.eye(2) * (params.pos_cov_max * 0.99)
    assert goal_for(item, params).x == pytest.approx(2.0 - params.standoff)
    item.cov = np.eye(2) * (params.pos_cov_max * 1.01)
    assert same_pose(goal_for(item, params), item.view_pose)


def test_goal_for_view_pose_closer_than_standoff_turns_in_place(params):
    item = make_item(1, mu=(0.3, 0.3), view=(0.0, 0.0, -1.0))
    goal = goal_for(item, params)
    assert (goal.x, goal.y) == (0.0, 0.0)
    assert goal.yaw == pytest.approx(math.pi / 4)


def test_goal_for_degenerate_cases_return_view_pose(params):
    item = make_item(1, mu=(1.0, 1.0), view=(1.0, 1.0, 0.4))
    assert same_pose(goal_for(item, params), item.view_pose)
    item = make_item(2, mu=(2.0, 0.0), view=(0.0, 0.0, 0.4))
    item.cov = np.array([[np.nan, 0.0], [0.0, 0.01]])
    assert same_pose(goal_for(item, params), item.view_pose)


def test_goal_for_does_not_alias_view_pose(params):
    item = make_item(1, cov=10.0)
    goal = goal_for(item, params)
    goal.x += 5.0
    assert item.view_pose.x == 0.0


# ------------------------------------------------------------------ find
def test_first_candidate_found(params):
    items = [make_item(1), make_item(2, mu=(0.0, 3.0))]
    memory, nav = FakeMemory(items), FakeNavigator()
    verifier, embedder = FakeVerifier([(True, 0.9)]), FakeEmbedder()
    clock = Clock()

    result = find("the blue mug", memory, embedder, nav, verifier, params, clock=clock)

    assert result.status == "found"
    assert result.item is items[0]
    assert result.tried == [(1, "found")]
    assert embedder.texts == ["the blue mug"]
    assert verifier.texts == ["the blue mug"]
    assert len(nav.goals) == 1
    assert same_pose(nav.goals[0], goal_for(items[0], params))
    assert [i for i, _ in memory.found] == [1]
    assert memory.not_found == []
    # The query uses the embedded text and the clock time.
    emb, t, k = memory.query_calls[0]
    assert np.array_equal(emb, unit(0))
    assert t == 1000.0
    assert memory.found[0][1] > t


def test_first_fails_then_second_found(params):
    items = [make_item(1), make_item(2, mu=(0.0, 3.0)), make_item(3, mu=(5.0, 5.0))]
    memory, nav = FakeMemory(items), FakeNavigator()
    verifier = FakeVerifier([(False, 0.1), (True, 0.8)])

    result = find("mug", memory, FakeEmbedder(), nav, verifier, params)

    assert result.status == "found"
    assert result.item is items[1]
    assert result.tried == [(1, "not_found"), (2, "found")]
    assert [i for i, _ in memory.not_found] == [1]
    assert [i for i, _ in memory.found] == [2]
    assert len(nav.goals) == 2  # the third candidate is never visited
    assert same_pose(nav.goals[1], goal_for(items[1], params))


def test_all_candidates_fail(params):
    items = [make_item(1), make_item(2), make_item(3)]
    memory = FakeMemory(items)
    result = find("mug", memory, FakeEmbedder(), FakeNavigator(), FakeVerifier(), params)

    assert result.status == "not_found"
    assert result.item is None
    assert result.tried == [(1, "not_found"), (2, "not_found"), (3, "not_found")]
    assert [i for i, _ in memory.not_found] == [1, 2, 3]
    assert memory.found == []


def test_nav_fails_then_view_pose_retry_succeeds(params):
    item = make_item(1, mu=(2.0, 0.0), view=(0.2, 0.1, 0.3))
    memory, nav = FakeMemory([item]), FakeNavigator([False, True])
    verifier = FakeVerifier([(True, 0.7)])

    result = find("mug", memory, FakeEmbedder(), nav, verifier, params)

    assert result.status == "found"
    assert result.tried == [(1, "found")]
    assert len(nav.goals) == 2
    assert same_pose(nav.goals[0], goal_for(item, params))
    assert same_pose(nav.goals[1], item.view_pose)
    assert len(verifier.texts) == 1


def test_nav_fails_twice_records_nav_failed_and_continues(params):
    items = [make_item(1), make_item(2, mu=(0.0, 3.0))]
    memory, nav = FakeMemory(items), FakeNavigator([False, False, True])
    verifier = FakeVerifier([(True, 0.9)])

    result = find("mug", memory, FakeEmbedder(), nav, verifier, params)

    assert result.status == "found"
    assert result.item is items[1]
    assert result.tried == [(1, "nav_failed"), (2, "found")]
    assert len(nav.goals) == 3
    assert len(verifier.texts) == 1  # no re-check where the robot never arrived
    # An unreachable candidate is not evidence about the object.
    assert memory.not_found == []


def test_nav_fails_everywhere(params):
    items = [make_item(1), make_item(2)]
    memory, nav = FakeMemory(items), FakeNavigator([False] * 4)
    verifier = FakeVerifier()

    result = find("mug", memory, FakeEmbedder(), nav, verifier, params)

    assert result.status == "nav_failed"
    assert result.item is None
    assert result.tried == [(1, "nav_failed"), (2, "nav_failed")]
    assert verifier.texts == []
    assert memory.found == [] and memory.not_found == []


def test_nav_failed_and_not_found_mix_is_not_found(params):
    items = [make_item(1), make_item(2)]
    nav = FakeNavigator([False, False, True])
    result = find("mug", FakeMemory(items), FakeEmbedder(), nav, FakeVerifier([(False, 0.2)]), params)
    assert result.status == "not_found"
    assert result.tried == [(1, "nav_failed"), (2, "not_found")]


def test_empty_memory(params):
    memory, nav, verifier = FakeMemory([]), FakeNavigator(), FakeVerifier()
    result = find("mug", memory, FakeEmbedder(), nav, verifier, params)
    assert result.status == "empty"
    assert result.item is None
    assert result.tried == []
    assert nav.goals == [] and verifier.texts == []


def test_navigator_exception_counts_as_failure(params):
    items = [make_item(1), make_item(2)]
    nav = FakeNavigator([RuntimeError("action server gone"), False, True])
    result = find("mug", FakeMemory(items), FakeEmbedder(), nav, FakeVerifier([(True, 0.9)]), params)
    assert result.tried == [(1, "nav_failed"), (2, "found")]


def test_verifier_exception_does_not_touch_memory(params):
    items = [make_item(1), make_item(2)]
    memory = FakeMemory(items)
    verifier = FakeVerifier([IOError("worker down"), (True, 0.9)])
    result = find("mug", memory, FakeEmbedder(), FakeNavigator(), verifier, params)
    assert result.tried == [(1, "not_found"), (2, "found")]
    assert memory.not_found == []
    assert [i for i, _ in memory.found] == [2]


def test_status_callback(params):
    lines = []
    items = [make_item(1, label="cup")]
    find("mug", FakeMemory(items), FakeEmbedder(), FakeNavigator(), FakeVerifier([(True, 0.9)]),
         params, on_status=lines.append)
    assert lines[0] == "query: mug"
    assert lines[-1] == "done: found"
    assert any("#1 (cup)" in line for line in lines)

    def broken(_):
        raise ValueError("listener bug")

    result = find("mug", FakeMemory(items), FakeEmbedder(), FakeNavigator(), FakeVerifier([(True, 0.9)]),
                  params, on_status=broken)
    assert result.status == "found"


# ------------------------------------------------------------------ log
def test_log_file_one_json_line_per_query(params, tmp_path):
    log = str(tmp_path / "logs" / "search.jsonl")  # the folder is created
    items = [make_item(1, mu=(2.0, 0.0), p=0.6, label="cup"), make_item(2, mu=(0.0, 3.0), p=0.9)]
    memory = FakeMemory(items)
    nav = FakeNavigator([False, True, True])
    verifier = FakeVerifier([(False, 0.2), (True, 0.85)])

    find("the blue mug", memory, FakeEmbedder(), nav, verifier, params, clock=Clock(), log_path=log)
    find("nothing", FakeMemory([]), FakeEmbedder(), FakeNavigator(), FakeVerifier(), params, log_path=log)

    with open(log, "r", encoding="utf-8") as fh:
        lines = fh.read().splitlines()
    assert len(lines) == 2
    first = json.loads(lines[0])
    assert read_log(log)[0] == first

    assert first["query"] == "the blue mug"
    assert first["status"] == "found"
    assert first["found_id"] == 2
    assert first["t_start"] == 1000.0
    assert first["t_end"] > first["t_start"]
    assert [c["id"] for c in first["candidates"]] == [1, 2]
    c0 = first["candidates"][0]
    assert c0 == {"id": 1, "label": "cup", "sim": pytest.approx(0.3), "p": 0.6,
                  "score": pytest.approx(2.0 / 3.0), "mu": [2.0, 0.0]}
    assert first["candidates"][1]["label"] is None

    v0, v1 = first["visits"]
    assert v0["id"] == 1 and v0["outcome"] == "not_found"
    assert v0["retried_view_pose"] is True
    assert v0["prob"] == pytest.approx(0.2)
    assert v0["goal"] == pytest.approx([2.0 - params.standoff, 0.0, 0.0])
    assert v0["t_end"] > v0["t_start"] >= first["t_start"]
    assert v1["id"] == 2 and v1["outcome"] == "found"
    assert v1["retried_view_pose"] is False
    assert v1["prob"] == pytest.approx(0.85)
    assert v1["t_start"] >= v0["t_end"]

    second = json.loads(lines[1])
    assert second["status"] == "empty"
    assert second["found_id"] is None
    assert second["candidates"] == [] and second["visits"] == []


def test_log_records_nav_failure_and_errors(params, tmp_path):
    log = str(tmp_path / "search.jsonl")
    nav = FakeNavigator([RuntimeError("boom"), False])
    find("mug", FakeMemory([make_item(1)]), FakeEmbedder(), nav, FakeVerifier(), params, log_path=log)
    record = read_log(log)[0]
    assert record["status"] == "nav_failed"
    visit = record["visits"][0]
    assert visit["outcome"] == "nav_failed"
    assert visit["prob"] is None
    assert "boom" in visit["error"]


def test_log_snapshot_is_taken_before_memory_updates(params, tmp_path):
    log = str(tmp_path / "search.jsonl")
    item = make_item(1, p=0.8)

    class LoweringMemory(FakeMemory):
        def mark_not_found(self, item_id, t):
            self._items[0].p = 0.1

    find("mug", LoweringMemory([item]), FakeEmbedder(), FakeNavigator(), FakeVerifier(), params, log_path=log)
    assert item.p == 0.1
    assert read_log(log)[0]["candidates"][0]["p"] == 0.8


def test_log_path_from_params_attribute(tmp_path):
    class LoggingParams(Params):
        pass

    params = LoggingParams()
    params.search_log = str(tmp_path / "from_params.jsonl")
    find("mug", FakeMemory([]), FakeEmbedder(), FakeNavigator(), FakeVerifier(), params)
    assert read_log(params.search_log)[0]["status"] == "empty"


def test_no_log_by_default(params, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    find("mug", FakeMemory([make_item(1)]), FakeEmbedder(), FakeNavigator(), FakeVerifier(), params)
    assert list(tmp_path.iterdir()) == []


def test_unwritable_log_does_not_break_search(params, tmp_path):
    result = find("mug", FakeMemory([make_item(1)]), FakeEmbedder(), FakeNavigator(),
                  FakeVerifier([(True, 0.9)]), params, log_path=str(tmp_path))  # a directory
    assert result.status == "found"
