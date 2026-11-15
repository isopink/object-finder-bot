import math

import numpy as np
import pytest

from objmem import geometry
from objmem.sim.runner import Sim, intrinsic_hfov, sim_params
from objmem.sim.sensors import LabelVerifier, SimCamera, SimNavigator, SimVerifier, query_label
from objmem.sim.world import EMB_DIM, ToyWorld, patrol_path
from objmem.types import Params, Pose2D


def test_world_has_ten_objects_on_desks():
    w = ToyWorld()
    assert len(w.objects) == 10
    for o in w.objects.values():
        assert any(d.contains(o.x, o.y) for d in w.desks), o.name


def test_embeddings_text_matches_its_object():
    w = ToyWorld()
    s = w.space
    rng = np.random.default_rng(0)
    imgs = {n: s.image_embedding(o, rng) for n, o in w.objects.items()}
    for v in imgs.values():
        assert v.shape == (EMB_DIM,)
        assert abs(float(np.linalg.norm(v)) - 1.0) < 1e-5
    # two noisy views of the same object pass the association gate (0.8); different objects do not
    a = s.image_embedding(w.object("blue_mug"), rng)
    b = s.image_embedding(w.object("blue_mug"), rng)
    c = s.image_embedding(w.object("red_mug"), rng)
    assert float(a @ b) > 0.85
    assert float(a @ c) < 0.8
    # the text picks its own object
    for text, target in [("Where is the blue mug?", "blue_mug"), ("a plastic cup with a straw", "plastic_cup"),
                         ("a black charger next to the laptop", "black_charger"),
                         ("Where is the silver laptop?", "silver_laptop")]:
        q = s.text_embedding(text)
        best = max(imgs, key=lambda n: float(imgs[n] @ q))
        assert best == target, text
    # CLIP-like magnitudes: text-image cosines well below image-image cosines
    q = s.text_embedding("Where is the blue mug?")
    assert 0.2 < float(imgs["blue_mug"] @ q) < 0.6


def test_detections_depth_and_nodepth():
    for mode in ("depth", "nodepth"):
        w = ToyWorld()
        p = sim_params(mode)
        cam = SimCamera(w, p, seed=1, det_rate=1.0, fp_rate=0.0)
        pose = Pose2D(1.0, 2.8, math.pi / 2)
        dets = cam.detect(pose)
        assert dets, mode
        for d in dets:
            l, t, r, b = d.box
            assert 0 <= l <= r < p.img_w and 0 <= t <= b < p.img_h
            assert (d.depth_m is not None) == (mode == "depth")


def test_depth_detection_back_projects_to_truth():
    w = ToyWorld()
    p = sim_params("depth")
    cam = SimCamera(w, p, seed=2, det_rate=1.0, fp_rate=0.0, pixel_noise=0.0)
    pose = Pose2D(0.8, 2.8, math.pi / 2)
    dets = cam.detect(pose)
    mug = w.object("blue_mug")
    errs = []
    for d in dets:
        ob = geometry.observe(d, pose, p, w.t)
        assert ob is not None
        errs.append(math.hypot(ob.mu[0] - mug.x, ob.mu[1] - mug.y))
    assert min(errs) < 0.1


def test_sim_projection_matches_geometry_project():
    w = ToyWorld()
    p = sim_params("depth")
    p.cam_pitch = 0.1
    p.cam_yaw = 0.05
    cam = SimCamera(w, p)
    pose = Pose2D(1.2, 2.6, 1.4)
    o = w.object("blue_mug")
    mine = cam.project("blue_mug", pose)
    ref = geometry.project(np.array([o.x, o.y, o.z]), pose, p)
    assert mine is not None and ref is not None
    assert np.allclose(mine, ref, atol=1e-6)


def test_false_positives_and_miss_rate():
    w = ToyWorld()
    p = sim_params("depth")
    pose = Pose2D(1.0, 2.8, math.pi / 2)
    n_visible = len(SimCamera(w, p).visible(pose))
    only_fp = SimCamera(w, p, seed=3, det_rate=0.0, fp_rate=2.0)
    n_fp = sum(len(only_fp.detect(pose)) for _ in range(200))
    assert 300 < n_fp < 500  # Poisson(2) per frame
    half = SimCamera(w, p, seed=3, det_rate=0.5, fp_rate=0.0)
    n_det = sum(len(half.detect(pose)) for _ in range(200))
    assert 0.4 < n_det / (200.0 * n_visible) < 0.6


def test_move_object_changes_detections():
    w = ToyWorld()
    p = sim_params("depth")
    cam = SimCamera(w, p, seed=0, det_rate=1.0, fp_rate=0.0)
    pose = Pose2D(0.8, 2.8, math.pi / 2)
    assert "blue_mug" in cam.visible(pose)
    w.move("blue_mug", 5.0, 0.65)
    assert "blue_mug" not in cam.visible(pose)
    assert w.moves and w.moves[0][1] == "blue_mug"


def test_patrol_path_poses_are_free():
    w = ToyWorld()
    for part in ("full", "north", "south", "east"):
        path = patrol_path(w, part)
        assert path
        for pose in path:
            assert w.is_free(pose.x, pose.y)


def test_navigator_rejects_desks_and_walls():
    w = ToyWorld()
    nav = SimNavigator(w)
    t0 = w.t
    assert not nav.go_to(Pose2D(1.0, 4.5, 0.0))   # on desk_a
    assert not nav.go_to(Pose2D(-1.0, 2.0, 0.0))  # outside
    assert nav.go_to(Pose2D(2.0, 2.0, 0.0))
    assert (w.robot.x, w.robot.y) == (2.0, 2.0)
    assert w.t > t0


def test_verifier_looks_at_ground_truth():
    w = ToyWorld()
    p = sim_params("depth")
    v = SimVerifier(w, p, seed=0)
    w.set_robot(Pose2D(0.9, 3.7, math.pi / 2))      # in front of the blue mug
    found, prob = v.check("Where is the blue mug?")
    assert found and prob > 0.9
    found, prob = v.check("Where is the red mug?")   # red mug is 2.6 m to the right
    assert not found
    w.set_robot(Pose2D(0.9, 3.7, -math.pi / 2))     # facing away
    assert not v.check("Where is the blue mug?")[0]


def test_label_verifier_and_query_label():
    assert query_label("Where is the blue mug?") == "cup"
    assert query_label("a black charger next to the laptop") is None
    assert query_label("find my black smartphone") == "cell phone"
    w = ToyWorld()
    p = sim_params("depth")
    lv = LabelVerifier(w, p, det_rate=1.0)
    w.set_robot(Pose2D(0.9, 3.7, math.pi / 2))
    assert lv.check("Where is the red mug?")[0]  # any cup counts: the weakness of label matching


def test_sim_params_clip_hfov_to_intrinsics():
    p = sim_params("depth")
    assert p.hfov == pytest.approx(intrinsic_hfov(Params()))
    assert p.hfov < Params().hfov


@pytest.mark.parametrize("mode", ["depth", "nodepth"])
def test_patrol_query_found_within_half_meter(mode):
    sim = Sim(mode=mode, seed=0)
    sim.patrol()
    mug = sim.world.object("blue_mug")
    r = sim.ask("Where is the blue mug?")
    assert r.status == "found"
    assert math.hypot(r.item.mu[0] - mug.x, r.item.mu[1] - mug.y) < 0.5


def test_seeded_runs_are_deterministic():
    def run(seed):
        sim = Sim(mode="nodepth", seed=seed)
        sim.patrol()
        r = sim.ask("Where is the green tumbler?")
        return [(it.id, round(float(it.mu[0]), 9), round(float(it.mu[1]), 9), round(it.p, 9))
                for it in sim.memory.items], r.tried, sim.world.t
    assert run(4) == run(4)
    assert run(4) != run(5)
