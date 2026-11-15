import math

import numpy as np
import pytest

from objmem import geometry
from objmem.bearing import wrap_angle
from objmem.geometry import in_view, make_in_view, median_depth, observe, project
from objmem.types import Detection, Params, Pose2D

EMB = np.ones(512, dtype=np.float32) / math.sqrt(512.0)


def detection_of(p_map, pose, params, with_depth=True, half=20):
    """Synthesize the detection an ideal camera would produce for a 3-D map point."""
    u, v, z = project(np.asarray(p_map, dtype=float), pose, params)
    # Keep the exact center: box (u - half, ..., u + half) has center u even if not integer.
    box = (u - half, v - half, u + half, v + half)
    return Detection(box=box, label="mug", conf=0.9, embedding=EMB, depth_m=z if with_depth else None)


POSES = [Pose2D(0.0, 0.0, 0.0), Pose2D(1.0, -1.0, 1.2), Pose2D(3.5, 0.5, 2.8),
         Pose2D(-0.5, 2.5, -0.6), Pose2D(2.5, 3.5, -1.9)]
TARGET = np.array([2.0, 1.5, 0.75])  # a mug on a desk


def mounted_params(**kw):
    params = Params()
    params.cam_x = 0.12
    params.cam_y = -0.03
    params.cam_z = 0.62
    params.cam_yaw = 0.1
    params.cam_pitch = 0.2
    for k, v in kw.items():
        setattr(params, k, v)
    return params


# ------------------------------------------------------------ transforms
def test_cam_map_round_trip():
    params = mounted_params()
    pose = Pose2D(1.0, 2.0, 0.7)
    p = np.array([0.3, -0.2, 1.7])
    assert geometry.map_to_cam(geometry.cam_to_map(p, pose, params), pose, params) == pytest.approx(p)


def test_optical_axis_points_forward_with_no_mount_rotation():
    params = Params()
    params.cam_x, params.cam_y, params.cam_z = 0.0, 0.0, 0.6
    pose = Pose2D(0.0, 0.0, 0.0)
    # Image center, 2 m deep -> 2 m straight ahead of the robot at camera height.
    p = geometry.cam_to_map(2.0 * geometry.pixel_ray(params.cx, params.cy, params), pose, params)
    assert p == pytest.approx([2.0, 0.0, 0.6])
    # A pixel right of center lands to the right (negative y); below center lands lower.
    p = geometry.cam_to_map(geometry.pixel_ray(params.cx + 100, params.cy + 100, params), pose, params)
    assert p[1] < 0 and p[2] < 0.6


# ------------------------------------------------------------ depth mode
@pytest.mark.parametrize("pose", POSES)
def test_depth_reprojects_known_point_from_several_poses(pose):
    params = mounted_params()
    if not in_view(TARGET[:2], pose, params):
        pose = Pose2D(pose.x, pose.y, math.atan2(TARGET[1] - pose.y, TARGET[0] - pose.x))
    det = detection_of(TARGET, pose, params)
    obs = observe(det, pose, params, t=12.5)
    assert obs is not None
    assert obs.mu == pytest.approx(TARGET[:2], abs=1e-9)
    assert obs.bearing is None
    assert obs.t == 12.5
    assert obs.label == "mug"
    assert (obs.view_pose.x, obs.view_pose.y, obs.view_pose.yaw) == (pose.x, pose.y, pose.yaw)
    assert obs.embedding.shape == (512,)


def test_depth_integer_box_is_close():
    params = Params()
    pose = Pose2D(0.0, 0.0, math.atan2(1.5, 2.0))
    det = detection_of(TARGET, pose, params)
    det.box = tuple(int(round(c)) for c in det.box)
    obs = observe(det, pose, params, t=0.0)
    assert np.linalg.norm(obs.mu - TARGET[:2]) < 0.01


def test_mount_offset_yaw_and_pitch_are_applied():
    base = Params()
    base.cam_x, base.cam_y, base.cam_z, base.cam_yaw, base.cam_pitch = 0.0, 0.0, 0.6, 0.0, 0.0
    pose = Pose2D(0.0, 0.0, 0.0)
    det = Detection(box=(300, 220, 340, 260), label="x", conf=1.0, embedding=EMB, depth_m=2.0)
    mu0 = observe(det, pose, base, 0.0).mu
    assert mu0 == pytest.approx([2.0, 0.0])

    # Offset: the same image moves with the camera.
    off = Params()
    off.cam_x, off.cam_y, off.cam_z, off.cam_yaw, off.cam_pitch = 0.2, 0.1, 0.6, 0.0, 0.0
    assert observe(det, pose, off, 0.0).mu == pytest.approx([2.2, 0.1])

    # Yaw: the camera looks 90 degrees left, so the center pixel is to the left.
    yaw = Params()
    yaw.cam_x, yaw.cam_y, yaw.cam_z, yaw.cam_yaw, yaw.cam_pitch = 0.0, 0.0, 0.6, math.pi / 2, 0.0
    assert observe(det, pose, yaw, 0.0).mu == pytest.approx([0.0, 2.0], abs=1e-9)

    # Pitch: tilted down by 30 degrees, the center ray reaches 2 m * cos(30) ahead.
    pit = Params()
    pit.cam_x, pit.cam_y, pit.cam_z, pit.cam_yaw, pit.cam_pitch = 0.0, 0.0, 0.6, 0.0, math.radians(30)
    assert observe(det, pose, pit, 0.0).mu == pytest.approx([2.0 * math.cos(math.radians(30)), 0.0])
    # And the 3-D point is below the camera.
    p3 = geometry.cam_to_map(2.0 * geometry.pixel_ray(320, 240, pit), pose, pit)
    assert p3[2] == pytest.approx(0.6 - 2.0 * math.sin(math.radians(30)))

    # Robot pose is applied after the mount.
    rp = Pose2D(1.0, 1.0, math.pi)
    assert observe(det, rp, off, 0.0).mu == pytest.approx([1.0 - 2.2, 1.0 - 0.1])


def test_depth_cov_grows_with_range_and_is_aligned_with_ray():
    params = Params()
    params.cam_x, params.cam_y, params.cam_z = 0.0, 0.0, 0.0
    pose = Pose2D(0.0, 0.0, 0.0)
    prev_along = 0.0
    prev_across = 0.0
    for r in (0.5, 1.0, 2.0, 3.5):
        ang = 0.3
        target = np.array([r * math.cos(ang), r * math.sin(ang), 0.0])
        obs = observe(detection_of(target, pose, params), pose, params, 0.0)
        along = np.array([math.cos(ang), math.sin(ang)])
        across = np.array([-math.sin(ang), math.cos(ang)])
        var_along = along @ obs.cov @ along
        var_across = across @ obs.cov @ across
        sr = params.sigma_range_a + params.sigma_range_b * r * r
        assert var_along == pytest.approx(sr ** 2)
        assert var_across == pytest.approx((r * params.sigma_bearing) ** 2)
        assert along @ obs.cov @ across == pytest.approx(0.0, abs=1e-12)
        assert var_along > prev_along and var_across > prev_across
        prev_along, prev_across = var_along, var_across
        assert np.allclose(obs.cov, obs.cov.T)


@pytest.mark.parametrize("depth", [None, 0.0, 0.1, 4.5, float("nan")])
def test_depth_missing_or_out_of_range_is_none(depth):
    params = Params()
    det = Detection(box=(300, 220, 340, 260), label="x", conf=1.0, embedding=EMB, depth_m=depth)
    assert observe(det, Pose2D(0.0, 0.0, 0.0), params, 0.0) is None


def test_unknown_mode_raises():
    params = Params()
    params.camera_mode = "stereo"
    det = Detection(box=(300, 220, 340, 260), label="x", conf=1.0, embedding=EMB, depth_m=1.0)
    with pytest.raises(ValueError):
        observe(det, Pose2D(0.0, 0.0, 0.0), params, 0.0)


# ------------------------------------------------------------ nodepth mode
@pytest.mark.parametrize("pose", POSES)
def test_nodepth_bearing_points_at_object(pose):
    params = mounted_params(camera_mode="nodepth")
    pose = Pose2D(pose.x, pose.y, math.atan2(TARGET[1] - pose.y, TARGET[0] - pose.x) + 0.2)
    det = detection_of(TARGET, pose, params, with_depth=False)
    obs = observe(det, pose, params, 3.0)
    assert obs is not None
    true_b = math.atan2(TARGET[1] - pose.y, TARGET[0] - pose.x)
    # The bearing is measured from the robot center; the camera is offset by a few cm,
    # so it is exact only at nominal_range. The error stays well below sigma_bearing.
    assert abs(wrap_angle(obs.bearing - true_b)) < params.sigma_bearing
    r = params.nominal_range
    assert obs.mu == pytest.approx([pose.x + r * math.cos(obs.bearing), pose.y + r * math.sin(obs.bearing)])


def test_nodepth_bearing_exact_without_mount_offset():
    params = Params()
    params.camera_mode = "nodepth"
    params.cam_x = params.cam_y = 0.0
    pose = Pose2D(0.5, -0.5, 0.4)
    obs = observe(detection_of(TARGET, pose, params, with_depth=False), pose, params, 0.0)
    assert obs.bearing == pytest.approx(math.atan2(TARGET[1] - pose.y, TARGET[0] - pose.x), abs=1e-9)


def test_nodepth_bearing_from_column():
    params = Params()
    params.camera_mode = "nodepth"
    params.cam_x = params.cam_y = 0.0
    pose = Pose2D(0.0, 0.0, 1.0)
    center = Detection(box=(310, 0, 330, 100), label="x", conf=1.0, embedding=EMB)
    assert observe(center, pose, params, 0.0).bearing == pytest.approx(1.0)
    right = Detection(box=(610, 200, 630, 280), label="x", conf=1.0, embedding=EMB)
    expect = 1.0 - math.atan2(620 - params.cx, params.fx)
    assert observe(right, pose, params, 0.0).bearing == pytest.approx(expect)
    # Depth is ignored in nodepth mode.
    right.depth_m = 1.0
    assert observe(right, pose, params, 0.0).bearing == pytest.approx(expect)


def test_nodepth_cov_is_elongated_along_ray():
    params = mounted_params(camera_mode="nodepth")
    pose = Pose2D(0.0, 0.0, 0.5)
    obs = observe(detection_of(TARGET, pose, params, with_depth=False), pose, params, 0.0)
    vals, vecs = np.linalg.eigh(obs.cov)
    along = np.array([math.cos(obs.bearing), math.sin(obs.bearing)])
    assert abs(abs(vecs[:, -1] @ along) - 1.0) < 1e-9
    assert vals[-1] == pytest.approx(params.sigma_range_nodepth ** 2)
    assert vals[0] == pytest.approx((params.nominal_range * params.sigma_bearing) ** 2)
    assert vals[-1] / vals[0] > 50


# ------------------------------------------------------------ in_view
def test_in_view_depth_mode():
    params = Params()
    params.cam_x = params.cam_y = 0.0
    f = make_in_view(params)
    pose = Pose2D(0.0, 0.0, 0.0)
    assert f(np.array([2.0, 0.0]), pose)
    assert f(np.array([2.0, 2.0 * math.tan(0.59)]), pose)          # just inside hfov/2 = 0.6
    assert not f(np.array([2.0, 2.0 * math.tan(0.61)]), pose)           # just outside
    assert not f(np.array([-2.0, 0.0]), pose)                           # behind
    assert not f(np.array([0.2, 0.0]), pose)                            # closer than depth_min
    assert not f(np.array([4.5, 0.0]), pose)                            # beyond depth_max
    assert f(np.array([3.9, 0.0]), pose)
    turned = Pose2D(1.0, 1.0, math.pi / 2)
    assert f(np.array([1.0, 3.0]), turned)
    assert not f(np.array([3.0, 1.0]), turned)


def test_in_view_uses_camera_mount():
    params = Params()
    params.cam_x, params.cam_y, params.cam_yaw = 0.0, 0.0, math.pi / 2
    pose = Pose2D(0.0, 0.0, 0.0)
    assert in_view(np.array([0.0, 2.0]), pose, params)
    assert not in_view(np.array([2.0, 0.0]), pose, params)
    params.cam_yaw = 0.0
    params.cam_x = 0.5   # camera 0.5 m ahead: a point 0.7 m ahead of the robot is 0.2 m from the camera
    assert not in_view(np.array([0.7, 0.0]), pose, params)
    assert in_view(np.array([0.9, 0.0]), pose, params)


def test_in_view_nodepth_mode():
    params = Params()
    params.camera_mode = "nodepth"
    params.cam_x = params.cam_y = 0.0
    pose = Pose2D(0.0, 0.0, 0.0)
    assert in_view(np.array([0.2, 0.0]), pose, params)     # no depth_min without depth
    assert in_view(np.array([3.9, 0.0]), pose, params)
    assert not in_view(np.array([4.5, 0.0]), pose, params)
    assert not in_view(np.array([0.0, 2.0]), pose, params)


# ------------------------------------------------------------ median_depth
def test_median_depth_center_and_invalid():
    depth = np.zeros((100, 200), dtype=np.float32)
    depth[40:60, 80:120] = 1.5
    depth[50, 100] = 9.0           # one outlier; median ignores it
    assert median_depth(depth, (50, 20, 150, 80)) == pytest.approx(1.5)
    # The border of the box is far away but outside the central 30%.
    depth2 = np.full((100, 200), 3.0, dtype=np.float32)
    depth2[45:55, 95:105] = 1.0
    assert median_depth(depth2, (80, 40, 120, 60), frac=0.3) == pytest.approx(1.0)
    assert median_depth(depth2, (80, 40, 120, 60), frac=1.0) == pytest.approx(3.0)


def test_median_depth_none_cases():
    depth = np.zeros((50, 50), dtype=np.float32)
    assert median_depth(depth, (10, 10, 40, 40)) is None
    depth[:] = np.nan
    assert median_depth(depth, (10, 10, 40, 40)) is None
    assert median_depth(None, (10, 10, 40, 40)) is None
    assert median_depth(np.ones((50, 50)), (60, 60, 80, 80)) is None   # outside the image


def test_median_depth_tiny_box_and_border():
    depth = np.arange(100, dtype=np.float32).reshape(10, 10) + 1.0
    assert median_depth(depth, (5, 5, 6, 6)) == pytest.approx(depth[5, 5])
    # A box partly outside the image is clipped.
    assert median_depth(depth, (8, 8, 14, 14), frac=1.0) == pytest.approx(np.median(depth[8:10, 8:10]))
