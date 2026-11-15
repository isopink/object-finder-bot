"""End-to-end tests through the real modules (no hardware, no ROS).

A small toy room is simulated here directly from the brief's contract, so the
test does not depend on the internals of objmem.sim:

  camera projection (test side)  -> Detection with depth_m or without
  objmem.geometry.observe        -> Observation
  objmem.memory.ObjectMemory     -> update_frame / query / mark_*
  objmem.search.find             -> navigate + re-check loop

Both camera modes are covered. The same scenarios also run through the
objmem.sim toy world, and search.find runs with objmem.worker.ClientVerifier
against the fake vision worker on a free port.
"""
import math
import socket
import threading

import numpy as np
import pytest

from objmem.types import Detection, Params, Pose2D

geometry = pytest.importorskip("objmem.geometry")
memory_mod = pytest.importorskip("objmem.memory")
search = pytest.importorskip("objmem.search")

DESK_Z = 0.75  # object height above the floor (m)


# ---------------------------------------------------------------- toy world
def _unit(v):
    v = np.asarray(v, dtype=np.float32)
    return v / np.linalg.norm(v)


class World:
    """Named objects at map positions with distinct unit embeddings."""

    def __init__(self, seed=0):
        self.rng = np.random.RandomState(seed)
        names = ["blue mug", "red tumbler", "black charger", "green bottle", "white cup"]
        positions = [(2.0, 1.0), (2.0, -1.0), (-2.0, 1.0), (-2.0, -1.0), (0.0, 2.2)]
        self.base = {n: _unit(self.rng.randn(512)) for n in names}
        self.pos = {n: np.array(p, dtype=float) for n, p in zip(names, positions)}

    def image_embedding(self, name):
        return _unit(self.base[name] + 0.2 * self.rng.randn(512) / math.sqrt(512))

    def move(self, name, xy):
        self.pos[name] = np.array(xy, dtype=float)


class TextEmbedder:
    """Embedder whose text side knows the world's object names."""

    def __init__(self, world):
        self.world = world

    def embed_text(self, text):
        for name, vec in self.world.base.items():
            if name in text:
                return vec.copy()
        return _unit(np.ones(512))

    def embed_images(self, images):
        raise AssertionError("not used in these tests")


def camera_pose(pose, params):
    """Camera position (x, y) and heading in the map frame."""
    c, s = math.cos(pose.yaw), math.sin(pose.yaw)
    x = pose.x + c * params.cam_x - s * params.cam_y
    y = pose.y + s * params.cam_x + c * params.cam_y
    return x, y, pose.yaw + params.cam_yaw


def project(point_xy, pose, params):
    """Map point on a desk -> (u, v, z_depth) in the image, or None when not visible.

    Camera optical frame: z forward, x right, y down; cam_pitch = 0 in these tests.
    """
    cx_m, cy_m, heading = camera_pose(pose, params)
    dx, dy = point_xy[0] - cx_m, point_xy[1] - cy_m
    fwd = math.cos(heading) * dx + math.sin(heading) * dy
    left = -math.sin(heading) * dx + math.cos(heading) * dy
    up = DESK_Z - params.cam_z
    if fwd <= 0.05:
        return None
    u = params.cx + params.fx * (-left) / fwd
    v = params.cy + params.fy * (-up) / fwd
    if not (0 <= u < params.img_w and 0 <= v < params.img_h):
        return None
    if abs(math.atan2(left, fwd)) > params.hfov / 2:
        return None
    if not (params.depth_min <= fwd <= params.depth_max):
        return None
    return u, v, fwd


def detections_at(world, pose, params, mode):
    out = []
    for name, xy in world.pos.items():
        uvz = project(xy, pose, params)
        if uvz is None:
            continue
        u, v, z = uvz
        half = max(6, int(40.0 / z))
        box = (int(u) - half, int(v) - half, int(u) + half, int(v) + half)
        depth = float(z) if mode == "depth" else None
        out.append((name, Detection(box=box, label="object", conf=0.9,
                                    embedding=world.image_embedding(name), depth_m=depth)))
    return out


PATROL = [Pose2D(0.0, 0.0, a) for a in np.linspace(-math.pi, math.pi, 16, endpoint=False)] + \
         [Pose2D(0.8, 0.0, 0.0), Pose2D(0.8, 0.0, 0.5), Pose2D(0.8, 0.0, -0.5),
          Pose2D(-0.8, 0.0, math.pi), Pose2D(-0.8, 0.0, math.pi - 0.5), Pose2D(-0.8, 0.0, -math.pi + 0.5),
          Pose2D(0.0, 0.9, math.pi / 2), Pose2D(0.5, 0.9, math.pi / 2), Pose2D(-0.5, 0.9, math.pi / 2),
          Pose2D(0.0, -0.9, -math.pi / 2), Pose2D(0.5, -0.9, -math.pi / 2), Pose2D(-0.5, -0.9, -math.pi / 2)]


def patrol(world, mem, params, mode, t0, rounds=2):
    in_view = geometry.make_in_view(params)
    t = t0
    for _ in range(rounds):
        for pose in PATROL:
            obs = []
            for _name, det in detections_at(world, pose, params, mode):
                o = geometry.observe(det, pose, params, t)
                if o is not None:
                    obs.append(o)
            mem.update_frame(obs, pose, in_view, t)
            t += 1.0
    return t


class SimNavigator:
    def __init__(self):
        self.pose = Pose2D(0.0, 0.0, 0.0)
        self.goals = []

    def go_to(self, pose):
        self.goals.append(pose)
        self.pose = Pose2D(pose.x, pose.y, pose.yaw)
        return True


class SimVerifier:
    """Found when the queried object is within 3 m of the robot and in front of it."""

    def __init__(self, world, nav):
        self.world, self.nav = world, nav

    def check(self, text):
        p = self.nav.pose
        for name, xy in self.world.pos.items():
            if name not in text:
                continue
            dx, dy = xy[0] - p.x, xy[1] - p.y
            rng = math.hypot(dx, dy)
            bearing = math.atan2(dy, dx) - p.yaw
            bearing = math.atan2(math.sin(bearing), math.cos(bearing))
            if rng < 3.0 and abs(bearing) < 0.6:
                return True, 0.9
        return False, 0.1


def _params(mode):
    params = Params()
    params.camera_mode = mode
    params.cam_pitch = 0.0
    return params


# ---------------------------------------------------------------- tests
@pytest.mark.parametrize("mode", ["depth", "nodepth"])
def test_patrol_query_found(mode):
    params = _params(mode)
    world = World(seed=1)
    emb = TextEmbedder(world)
    mem = memory_mod.ObjectMemory(params)
    t = patrol(world, mem, params, mode, t0=1000.0)
    assert mem.items

    cands = mem.query(emb.embed_text("the blue mug"), t)
    assert cands
    err = np.linalg.norm(np.asarray(cands[0].item.mu) - world.pos["blue mug"])
    assert err < 0.5, "remembered position off by {:.2f} m".format(err)

    nav = SimNavigator()
    res = search.find("where is the blue mug", mem, emb, nav, SimVerifier(world, nav), params,
                      clock=lambda: t)
    assert res.status == "found"
    assert np.linalg.norm(np.asarray(res.item.mu) - world.pos["blue mug"]) < 0.5


@pytest.mark.parametrize("mode", ["depth", "nodepth"])
def test_moved_object(mode):
    params = _params(mode)
    world = World(seed=2)
    emb = TextEmbedder(world)
    mem = memory_mod.ObjectMemory(params)
    t = patrol(world, mem, params, mode, t0=1000.0)

    old_pos = world.pos["blue mug"].copy()
    old = mem.query(emb.embed_text("blue mug"), t)[0].item
    assert np.linalg.norm(np.asarray(old.mu) - old_pos) < 0.5
    old_id, old_p = old.id, old.p

    # Move the mug to an empty spot, then ask before patrolling: the old place fails.
    world.move("blue mug", (0.0, -2.2))
    nav = SimNavigator()
    res = search.find("blue mug", mem, emb, nav, SimVerifier(world, nav), params, clock=lambda: t)
    assert (old_id, "not_found") in res.tried
    by_id = {it.id: it for it in mem.items}
    assert by_id[old_id].p < old_p, "confidence of the old place did not drop"

    # Patrol again: the old memory decays, a new one appears where the mug is now.
    t = patrol(world, mem, params, mode, t0=t + 10.0)
    by_id = {it.id: it for it in mem.items}
    if old_id in by_id:
        assert by_id[old_id].p < old_p
    nav = SimNavigator()
    res = search.find("blue mug", mem, emb, nav, SimVerifier(world, nav), params, clock=lambda: t)
    assert res.status == "found"
    assert np.linalg.norm(np.asarray(res.item.mu) - world.pos["blue mug"]) < 0.5


# ---------------------------------------------------------------- fake worker
def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture
def fake_worker():
    worker = pytest.importorskip("objmem.worker")
    embed = pytest.importorskip("objmem.embed")
    fakes = pytest.importorskip("objmem.fakes")
    params = Params()
    port = _free_port()
    server = worker.make_server(embedder=embed.FakeEmbedder(), detector=fakes.FakeDetector(),
                                camera=fakes.FakeCamera(mode="depth"), params=params,
                                host="127.0.0.1", port=port)
    th = threading.Thread(target=server.serve_forever, daemon=True)
    th.start()
    try:
        yield worker.VisionClient("http://127.0.0.1:{}".format(port))
    finally:
        server.shutdown()
        server.server_close()


@pytest.mark.parametrize("query, status", [("a red cup", "found"), ("a green plant", "not_found")])
def test_find_with_client_verifier_against_fake_worker(fake_worker, query, status):
    """Detections from the worker -> geometry -> memory -> search.find with ClientVerifier."""
    from objmem.worker import ClientEmbedder, ClientVerifier

    client = fake_worker
    params = Params()
    health = client.health()
    assert health["ok"] is True and health["camera"] is True

    pose = Pose2D(0.0, 0.0, 0.0)
    dets = client.detect_embed()
    assert dets and all(len(d.embedding) == 512 for d in dets)
    assert all(d.depth_m is not None for d in dets)
    obs = [o for o in (geometry.observe(d, pose, params, 100.0) for d in dets) if o is not None]
    assert obs
    mem = memory_mod.ObjectMemory(params)
    mem.update_frame(obs, pose, geometry.make_in_view(params), 100.0)
    assert len(mem.items) == len(obs)

    nav = SimNavigator()
    res = search.find(query, mem, ClientEmbedder(client), nav, ClientVerifier(client), params,
                      clock=lambda: 101.0)
    assert res.status == status
    assert nav.goals, "no Nav2 goal was sent"
    if status == "found":
        assert res.tried[0][1] == "found"
        assert res.item is not None and res.item.p > 0.7
    else:
        assert all(outcome == "not_found" for _, outcome in res.tried)
        assert all(it.p < params.p_init for it in mem.items)


# ---------------------------------------------------------------- objmem.sim toy world
@pytest.mark.parametrize("mode", ["depth", "nodepth"])
def test_sim_world_patrol_query_found(mode):
    from objmem.sim.runner import Sim, distance

    sim = Sim(mode=mode, seed=2)
    sim.patrol()
    res = sim.ask("Where is the blue mug?")
    assert res.status == "found"
    mug = sim.world.object("blue_mug")
    assert distance(res.item, (mug.x, mug.y)) < 0.5


@pytest.mark.parametrize("mode", ["depth", "nodepth"])
def test_sim_world_moved_object(mode):
    from objmem.sim.runner import Sim, distance

    sim = Sim(mode=mode, seed=2)
    sim.patrol()
    first = sim.ask("Where is the blue mug?")
    assert first.status == "found"
    old_id = first.item.id

    sim.world.move("blue_mug", 5.0, 0.65)
    sim.patrol(part="south")
    p_before = sim.memory.get(old_id).p
    res = sim.ask("Where is the blue mug?")
    assert res.status == "found"
    assert (old_id, "not_found") in res.tried, res.tried
    assert sim.memory.get(old_id).p < p_before
    assert distance(res.item, (5.0, 0.65)) < 0.5
