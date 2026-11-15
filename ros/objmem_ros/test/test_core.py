"""objmem_ros.core without ROS: run with  pytest ros/objmem_ros/test"""
import math
import os

import numpy as np
import pytest

from objmem.types import Detection, Params, Pose2D, SearchResult

from objmem_ros import compat, core

import helpers
from fake_worker import EMB_A, FakeWorker


def det(u=320, depth=2.0, emb=None):
    e = EMB_A if emb is None else emb
    return Detection(box=(u - 20, 200, u + 20, 280), label="mug", conf=0.9, embedding=e.copy(), depth_m=depth)


class RecordingMemory(object):
    def __init__(self):
        self.calls = []
        self._items = []
        self.saved = []

    @property
    def items(self):
        return self._items

    def update_frame(self, observations, pose, in_view, t):
        self.calls.append((observations, pose, t))

    def save(self, path):
        self.saved.append(path)


# ---------------------------------------------------------------- observer
def test_rate_limiter():
    r = core.RateLimiter(2.0)
    assert r.ready(0.0)
    assert not r.ready(0.3)
    assert r.ready(0.5)
    assert not r.ready(0.9)
    assert r.ready(1.0)


def test_motion_gate_requires_settle_time():
    g = core.MotionGate(lin_eps=0.02, ang_eps=0.03, settle_s=0.5)
    g.update(Pose2D(0, 0, 0), 0.0)
    assert not g.stopped(0.2)
    assert g.stopped(0.5)
    g.update(Pose2D(0.1, 0, 0), 0.6)  # moved
    assert not g.stopped(0.9)
    g.update(Pose2D(0.105, 0, 0), 1.0)  # below lin_eps: still
    assert g.stopped(1.1)
    g.update(Pose2D(0.105, 0, 0.1), 1.2)  # turned
    assert not g.stopped(1.5)
    assert g.stopped(1.7)


def test_observer_only_while_stopped_and_throttled():
    mem = RecordingMemory()
    oc = core.ObserverCore(mem, Params(), rate_hz=1.0, only_when_stopped=True, settle_s=0.5)
    calls = []

    def get():
        calls.append(1)
        return [det()]
    pose = Pose2D(0, 0, 0)
    assert oc.tick(pose, 0.0, get) is None          # not settled yet
    assert oc.tick(pose, 0.6, get) is not None      # settled -> step
    assert oc.tick(pose, 1.0, get) is None          # throttled
    assert oc.tick(Pose2D(0.5, 0, 0), 1.7, get) is None  # moving
    assert oc.tick(Pose2D(0.5, 0, 0), 2.3, get) is not None
    assert len(calls) == 2 and len(mem.calls) == 2


def test_observer_not_gated_when_disabled_and_paused():
    mem = RecordingMemory()
    oc = core.ObserverCore(mem, Params(), rate_hz=2.0, only_when_stopped=False)
    assert oc.tick(Pose2D(0, 0, 0), 0.0, lambda: [det()]) is not None
    oc.paused = True
    assert oc.tick(Pose2D(0, 0, 0), 5.0, lambda: [det()]) is None


def test_observer_step_places_detections_depth_mode():
    mem = RecordingMemory()
    p = Params()
    oc = core.ObserverCore(mem, p, observe=compat.fallback_observe, make_in_view=compat.fallback_make_in_view)
    pose = Pose2D(1.0, 2.0, math.pi / 2)
    s = oc.step([det(u=int(p.cx), depth=2.0), det(depth=None), det(depth=10.0)], pose, 3.0)
    obs, pose_seen, t = mem.calls[0]
    assert len(obs) == 1 and t == 3.0 and pose_seen == pose
    # straight ahead (north) of the camera, which sits cam_x in front of base_link
    assert obs[0].mu == pytest.approx([1.0, 2.0 + p.cam_x + 2.0], abs=1e-6)
    assert obs[0].bearing is None
    assert s == "observe: detections=3 observations=1 memories=0"


def test_observer_step_with_real_or_fallback_geometry():
    """Whatever geometry is installed: one centered detection, 2 m ahead, ends near x = 2 + cam_x."""
    mem = RecordingMemory()
    p = Params()
    oc = core.ObserverCore(mem, p)
    oc.step([det(u=int(p.cx), depth=2.0)], Pose2D(0, 0, 0), 1.0)
    obs = mem.calls[0][0]
    assert len(obs) == 1
    assert obs[0].mu[1] == pytest.approx(0.0, abs=0.05)
    assert 1.5 < obs[0].mu[0] < 2.6


def test_observer_nodepth_gives_bearing():
    mem = RecordingMemory()
    p = Params(camera_mode="nodepth")
    oc = core.ObserverCore(mem, p)
    oc.step([det(u=int(p.cx), depth=None)], Pose2D(0, 0, 0.5), 1.0)
    o = mem.calls[0][0][0]
    assert o.bearing == pytest.approx(0.5, abs=1e-3)
    w, v = np.linalg.eigh(o.cov)
    major = v[:, 1]
    assert abs(abs(major @ np.array([math.cos(0.5), math.sin(0.5)])) - 1.0) < 1e-3


def test_periodic_and_forced_save(tmp_path):
    mem = RecordingMemory()
    oc = core.ObserverCore(mem, Params(), only_when_stopped=False, save_path=str(tmp_path / "m.npz"),
                           save_period_s=10.0)
    assert not oc.maybe_save(0.0)
    oc.step([], Pose2D(0, 0, 0), 1.0)
    assert not oc.maybe_save(5.0)
    assert oc.maybe_save(10.0)
    assert not oc.maybe_save(25.0)   # nothing changed since
    assert oc.maybe_save(26.0, force=True)
    assert len(mem.saved) == 2


def test_mark_dirty_triggers_periodic_save(tmp_path):
    mem = RecordingMemory()
    oc = core.ObserverCore(mem, Params(), save_path=str(tmp_path / "m.npz"), save_period_s=1.0)
    oc.maybe_save(0.0)
    assert not oc.maybe_save(2.0)
    oc.mark_dirty()
    assert oc.maybe_save(3.0)


def test_no_save_without_path():
    oc = core.ObserverCore(RecordingMemory(), Params())
    assert not oc.maybe_save(100.0, force=True)


# ---------------------------------------------------------------- memory file
def test_shared_memory_save_load_roundtrip(tmp_path):
    p = Params()
    mem, loaded = core.load_or_create_memory(str(tmp_path / "mem"), p)
    assert not loaded and mem.items == []
    shared = core.SharedMemory(helpers.preload(mem, 100.0))
    shared.save(str(tmp_path / "mem"))
    assert os.path.exists(str(tmp_path / "mem.npz"))
    assert not os.path.exists(str(tmp_path / "mem.tmp.npz"))
    mem2, loaded = core.load_or_create_memory(str(tmp_path / "mem"), p)
    assert loaded and len(mem2.items) == 2
    got = sorted(tuple(np.round(it.mu, 6)) for it in mem2.items)
    assert got == sorted([helpers.POS_A, helpers.POS_B])


def test_file_watcher(tmp_path):
    path = str(tmp_path / "m.npz")
    w = core.FileWatcher(path)
    assert not w.changed()
    mem = helpers.preload(compat.memory_class()(Params()), 1.0)
    core.save_memory(mem, path)
    assert w.changed()
    assert not w.changed()


def test_fallback_memory_roundtrip_and_updates(tmp_path):
    p = Params()
    m = helpers.preload(compat.FallbackMemory(p), 0.0)
    q = m.query(helpers.EMB_A, 0.0)
    assert q[0].item.mu.tolist() == list(helpers.POS_A)
    first = q[0].item.id
    p0 = q[0].item.p
    m.mark_not_found(first, 1.0)
    assert m._get(first).p < p0
    m.mark_found(first, 2.0)
    m.save(str(tmp_path / "f.npz"))
    m2 = compat.FallbackMemory.load(str(tmp_path / "f.npz"), p)
    assert [i.p for i in m2.items] == pytest.approx([i.p for i in m.items])
    assert m2._next_id == m._next_id


# ---------------------------------------------------------------- depth and camera_info
def test_depth_from_16uc1_and_32fc1():
    a = np.array([[1000, 0], [2500, 65535]], dtype="<u2")
    d = core.depth_from_image_msg("16UC1", 2, 2, 4, a.tobytes())
    assert d.dtype == np.float32
    assert np.allclose(d, [[1.0, 0.0], [2.5, 65.535]])
    f = np.array([[1.5, np.nan]], dtype="<f4")
    d = core.depth_from_image_msg("32FC1", 1, 2, 8, f.tobytes())
    assert d.tolist() == [[1.5, 0.0]]
    with pytest.raises(ValueError):
        core.depth_from_image_msg("rgb8", 1, 1, 3, b"abc")


def test_depth_row_padding():
    a = np.array([[1000, 2000, 7]], dtype="<u2")  # step 6 bytes, width 2
    d = core.depth_from_image_msg("16UC1", 1, 2, 6, a.tobytes())
    assert d.shape == (1, 2)


def test_fill_depth_uses_median_and_scale():
    depth = np.zeros((240, 320), dtype=np.float32)
    depth[100:140, 150:170] = 1.8
    d = Detection(box=(300, 200, 340, 280), label="x", conf=1.0, embedding=EMB_A.copy(), depth_m=None)
    core.fill_depth([d], depth, median_depth=compat.fallback_median_depth, scale_xy=(0.5, 0.5))
    assert d.depth_m == pytest.approx(1.8)
    core.fill_depth([d], None)
    assert d.depth_m == pytest.approx(1.8)


def test_params_with_camera_info():
    p = core.params_with_camera_info(Params(), [600.0, 0, 330.0, 0, 610.0, 250.0, 0, 0, 1], 640, 480)
    assert (p.fx, p.fy, p.cx, p.cy, p.img_w, p.img_h) == (600.0, 610.0, 330.0, 250.0, 640, 480)
    assert p.hfov == pytest.approx(2 * math.atan2(320, 600))
    assert Params().fx == 615.0  # original untouched
    q = core.params_with_camera_info(Params(), [0.0] * 9, 640, 480)
    assert q.fx == 615.0


def test_yaw_quaternion_roundtrip():
    for yaw in (-3.0, -1.0, 0.0, 0.7, 3.1):
        assert core.yaw_from_quaternion(*core.quaternion_from_yaw(yaw)) == pytest.approx(yaw)


# ---------------------------------------------------------------- finder
class ScriptNav(object):
    def __init__(self, results):
        self.results = list(results)
        self.goals = []

    def go_to(self, pose):
        self.goals.append(pose)
        return self.results.pop(0) if self.results else True


class ScriptVerifier(object):
    def __init__(self, results):
        self.results = list(results)

    def check(self, text):
        f = self.results.pop(0)
        return f, 0.9 if f else 0.1


class FixedEmbedder(object):
    def embed_text(self, text):
        from fake_worker import EMB_QUERY
        return EMB_QUERY


def _finder(nav, ver, find=None):
    p = Params()
    mem = core.SharedMemory(helpers.preload(compat.memory_class()(p), 0.0))
    lines = []
    fc = core.FinderCore(mem, FixedEmbedder(), nav, ver, p, lines.append, find=find, clock=lambda: 1.0)
    return fc, lines


def _kinds(lines):
    return [l.split(":")[0] for l in lines]


@pytest.mark.parametrize("find", [None, compat.fallback_find], ids=["installed", "fallback"])
def test_finder_status_sequence_fail_then_found(find):
    nav = ScriptNav([True, True])
    fc, lines = _finder(nav, ScriptVerifier([False, True]), find)
    res = fc.run("where is the mug")
    assert res.status == "found"
    assert _kinds(lines) == ["query", "candidates", "goal_sent", "goal_reached", "recheck",
                             "goal_sent", "goal_reached", "recheck", "result"]
    assert lines[4].startswith("recheck: not_found") and lines[7].startswith("recheck: found")
    assert lines[-1].startswith("result: found")
    # first goal near A, second near B
    assert math.hypot(nav.goals[0].x - helpers.POS_A[0], nav.goals[0].y - helpers.POS_A[1]) < 1.0
    assert math.hypot(nav.goals[1].x - helpers.POS_B[0], nav.goals[1].y - helpers.POS_B[1]) < 1.0


def test_finder_reports_errors_and_busy():
    class Boom(object):
        def go_to(self, pose):
            raise RuntimeError("nav down")
    fc, lines = _finder(Boom(), ScriptVerifier([True]), compat.fallback_find)
    assert fc.run("mug") is None
    assert lines[-1] == "error: RuntimeError: nav down"
    fc._busy.acquire()
    assert fc.run("mug") is None
    assert lines[-1].startswith("busy:")
    fc._busy.release()
    assert fc.run("   ") is None


def test_status_result_strings():
    assert core.status_result(SearchResult("empty", None, [])) == "result: empty tried=[]"
    assert core.status_result(SearchResult("nav_failed", None, [(3, "nav_failed")])) == \
        "result: nav_failed tried=[3:nav_failed]"


def test_fallback_find_empty_and_nav_retry():
    p = Params()
    empty = compat.FallbackMemory(p)
    r = compat.fallback_find("x", empty, FixedEmbedder(), ScriptNav([]), ScriptVerifier([]), p)
    assert r.status == "empty"
    mem = helpers.preload(compat.FallbackMemory(p), 0.0)
    nav = ScriptNav([False, True, False, False])
    r = compat.fallback_find("x", mem, FixedEmbedder(), nav, ScriptVerifier([False]), p, clock=lambda: 1.0)
    assert [o for _, o in r.tried] == ["not_found", "nav_failed"]
    assert r.status == "not_found"


def test_fallback_goal_for():
    p = Params()
    mem = helpers.preload(compat.FallbackMemory(p), 0.0)
    a = [i for i in mem.items if i.mu[0] > 0][0]
    g = compat.fallback_goal_for(a, p)
    assert (g.x, g.y) == pytest.approx((2.0 - p.standoff, 0.0))
    assert g.yaw == pytest.approx(0.0)
    a.cov = np.diag([1.0, 0.01])
    assert compat.fallback_goal_for(a, p) == a.view_pose


# ---------------------------------------------------------------- worker client
def test_worker_client_against_fake_worker():
    dets = [{"box": [1, 2, 3, 4], "label": "mug", "conf": 0.5, "embedding": [1.0] + [0.0] * 511,
             "depth_m": None}]
    w = FakeWorker(0, [False, True], detections=dets).start()
    try:
        c = compat.vision_client(w.url, timeout=5.0)
        assert c.health()["ok"]
        v = compat.client_verifier(c)
        assert v.check("mug")[0] is False
        assert v.check("mug")[0] is True
        e = compat.ClientTextEmbedder(c).embed_text("mug")
        assert e.shape == (512,)
        got = compat.detect_embed_jpeg(w.url, b"\xff\xd8jpeg")
        assert got[0].box == (1, 2, 3, 4) and got[0].depth_m is None
        body = [c for c in w.calls if c[1] == "/detect_embed"][0][2]
        assert "image_jpeg_b64" in body
        assert compat.detect_embed_jpeg(w.url, None)[0].label == "mug"
        body = [c for c in w.calls if c[1] == "/detect_embed"][-1][2]
        assert "image_jpeg_b64" not in body
    finally:
        w.stop()


# ---------------------------------------------------------------- mapview helpers
def test_fallback_draw_map_png():
    mem = helpers.preload(compat.FallbackMemory(Params()), 0.0)
    png = compat.fallback_draw_map(mem.items, robot_pose=Pose2D(0, 0, 0))
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    assert compat.fallback_draw_map([])[:4] == b"\x89PNG"


def test_items_json_and_ellipse():
    mem = helpers.preload(compat.FallbackMemory(Params()), 0.0)
    j = core.items_json(mem.items)
    assert len(j) == 2 and set(j[0]) >= {"id", "x", "y", "p", "cov", "label"}
    major, minor, ang = core.ellipse_axes(np.diag([0.04, 0.01]))
    assert (major, minor) == pytest.approx((0.2, 0.1))
    assert abs(math.cos(ang)) == pytest.approx(1.0)
    assert "setInterval" in core.MAP_PAGE.format(refresh_ms=2000)


def test_ask_parse_command():
    from objmem_ros.ask import parse_command
    assert parse_command("q where is the mug") == ("query", "where is the mug")
    assert parse_command("q   ")[0] == "unknown"
    assert parse_command("v") == ("unknown", "v")
    assert parse_command("v", voice=True) == ("voice", "")
    assert parse_command("c")[0] == "cancel"
    assert parse_command("exit")[0] == "exit"
    assert parse_command("")[0] == "empty"


def test_probe_all_lists_only_missing_modules():
    missing = compat.probe_all()
    for name in missing:
        assert name.split(".")[0] in ("memory", "geometry", "search", "worker", "viz")
    try:
        import objmem.memory  # noqa: F401
        assert "memory" not in missing
    except ImportError:
        assert "memory" in missing
