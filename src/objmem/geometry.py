"""Camera -> map geometry (proposal 4.1) for both camera modes.

Frames:

- optical camera frame: x right, y down, z forward (pinhole, intrinsics fx, fy, cx, cy).
- camera body frame: x forward, y left, z up.
- base_link: the camera body frame is placed at (cam_x, cam_y, cam_z) and rotated
  by yaw ``cam_yaw`` (about z, positive = left) then pitch ``cam_pitch``
  (about y, positive = tilted down).
- map: base_link moved by the robot pose (x, y, yaw). Height is dropped at the end.

The depth from the RealSense is z-depth along the optical axis, so the point is
``P_c = d * K^-1 [u, v, 1]``. Python 3.8 compatible; numpy only.
"""
import math
from typing import Optional, Tuple

import numpy as np

from objmem.bearing import ray_covariance, ray_gaussian, wrap_angle
from objmem.types import Box, Detection, InView, Observation, Params, Pose2D

# --------------------------------------------------------------- transforms
_OPT_TO_BODY = np.array([[0.0, 0.0, 1.0],     # body x = optical z
                         [-1.0, 0.0, 0.0],    # body y = -optical x
                         [0.0, -1.0, 0.0]])   # body z = -optical y


def _rot_z(a: float) -> np.ndarray:
    c, s = math.cos(a), math.sin(a)
    return np.array([[c, -s, 0.0], [s, c, 0.0], [0.0, 0.0, 1.0]])


def _rot_y(a: float) -> np.ndarray:
    c, s = math.cos(a), math.sin(a)
    return np.array([[c, 0.0, s], [0.0, 1.0, 0.0], [-s, 0.0, c]])


def mount_rotation(params: Params) -> np.ndarray:
    """Rotation base_link <- optical camera frame."""
    return _rot_z(float(params.cam_yaw)) @ _rot_y(float(params.cam_pitch)) @ _OPT_TO_BODY


def camera_position(pose: Pose2D, params: Params) -> np.ndarray:
    """(3,) camera position in the map (z = height above the floor)."""
    t_base = np.array([params.cam_x, params.cam_y, params.cam_z], dtype=float)
    return np.array([pose.x, pose.y, 0.0]) + _rot_z(pose.yaw) @ t_base


def cam_to_map(p_opt: np.ndarray, pose: Pose2D, params: Params) -> np.ndarray:
    """Optical-frame point (3,) -> map point (3,)."""
    r_map_base = _rot_z(pose.yaw)
    p_base = np.array([params.cam_x, params.cam_y, params.cam_z], dtype=float) + mount_rotation(params) @ p_opt
    return np.array([pose.x, pose.y, 0.0]) + r_map_base @ p_base


def map_to_cam(p_map: np.ndarray, pose: Pose2D, params: Params) -> np.ndarray:
    """Map point (3,) -> optical-frame point (3,). Inverse of ``cam_to_map``."""
    r_map_base = _rot_z(pose.yaw)
    p_base = r_map_base.T @ (np.asarray(p_map, dtype=float) - np.array([pose.x, pose.y, 0.0]))
    t_base = np.array([params.cam_x, params.cam_y, params.cam_z], dtype=float)
    return mount_rotation(params).T @ (p_base - t_base)


def project(p_map: np.ndarray, pose: Pose2D, params: Params) -> Optional[Tuple[float, float, float]]:
    """Map point (3,) -> (u, v, z_depth) in the image, or None when behind the camera.
    Useful for simulators and tests."""
    pc = map_to_cam(p_map, pose, params)
    if pc[2] <= 1e-9:
        return None
    u = params.fx * pc[0] / pc[2] + params.cx
    v = params.fy * pc[1] / pc[2] + params.cy
    return float(u), float(v), float(pc[2])


def pixel_ray(u: float, v: float, params: Params) -> np.ndarray:
    """K^-1 [u, v, 1]: optical-frame ray with z = 1."""
    return np.array([(u - params.cx) / params.fx, (v - params.cy) / params.fy, 1.0])


def box_center(box: Box) -> Tuple[float, float]:
    left, top, right, bottom = box
    return 0.5 * (left + right), 0.5 * (top + bottom)


# --------------------------------------------------------------- observe
def _valid_depth(d: Optional[float], params: Params) -> bool:
    if d is None:
        return False
    try:
        d = float(d)
    except (TypeError, ValueError):
        return False
    return math.isfinite(d) and params.depth_min <= d <= params.depth_max


def observe(det: Detection, pose: Pose2D, params: Params, t: float) -> Optional[Observation]:
    """Place a detection on the map.

    depth mode: back-project the box center with ``det.depth_m``; covariance with
    range std ``sigma_range_a + sigma_range_b * r^2`` along the viewing ray and
    ``r * sigma_bearing`` across it (r = camera-to-object distance). Returns None
    when depth is missing or outside ``[depth_min, depth_max]``.

    nodepth mode: the map-frame bearing of the box center from the robot position,
    with ``mu``, ``cov`` from ``bearing.ray_gaussian``.
    """
    u, v = box_center(det.box)
    view_pose = Pose2D(float(pose.x), float(pose.y), float(pose.yaw))
    emb = np.asarray(det.embedding, dtype=np.float32)
    mode = params.camera_mode

    if mode == "nodepth":
        b = pixel_bearing(u, v, pose, params)
        if b is None:
            return None
        mu, cov = ray_gaussian(view_pose, b, params)
        return Observation(embedding=emb, mu=mu, cov=cov, t=float(t), view_pose=view_pose,
                           label=det.label, bearing=b)

    if mode != "depth":
        raise ValueError("camera_mode must be 'depth' or 'nodepth', got {!r}".format(mode))
    if not _valid_depth(det.depth_m, params):
        return None
    p_map = cam_to_map(float(det.depth_m) * pixel_ray(u, v, params), pose, params)
    cam = camera_position(pose, params)
    mu = p_map[:2].copy()
    delta = mu - cam[:2]
    r = float(np.linalg.norm(p_map - cam))
    if float(np.linalg.norm(delta)) > 1e-9:
        ray_angle = math.atan2(delta[1], delta[0])
    else:
        ray_angle = pose.yaw + params.cam_yaw
    sigma_r = params.sigma_range_a + params.sigma_range_b * r * r
    cov = ray_covariance(ray_angle, sigma_r, r * params.sigma_bearing)
    return Observation(embedding=emb, mu=mu, cov=cov, t=float(t), view_pose=view_pose,
                       label=det.label, bearing=None)


def pixel_bearing(u: float, v: float, pose: Pose2D, params: Params) -> Optional[float]:
    """Map-frame bearing (from the robot position) of the camera ray through pixel (u, v).

    The ray starts at the camera, which is offset from the robot center by the
    mount. The bearing is taken to the ray's point at ``nominal_range`` (horizontal
    distance) from the camera, so it matches ``ray_gaussian`` and an EKF that
    measures bearings from ``view_pose``. With pitch 0 it depends on ``u`` only.
    Returns None for a ray with no horizontal component.
    """
    d_map = _rot_z(pose.yaw) @ mount_rotation(params) @ pixel_ray(u, v, params)
    h = float(math.hypot(d_map[0], d_map[1]))
    if h < 1e-9:
        return None
    cam = camera_position(pose, params)
    r = float(params.nominal_range)
    px = cam[0] + r * d_map[0] / h
    py = cam[1] + r * d_map[1] / h
    if math.hypot(px - pose.x, py - pose.y) < 1e-9:
        return wrap_angle(math.atan2(d_map[1], d_map[0]))
    return wrap_angle(math.atan2(py - pose.y, px - pose.x))


# --------------------------------------------------------------- field of view
def in_view(mu: np.ndarray, pose: Pose2D, params: Params) -> bool:
    """True when the map point is inside the horizontal field of view ``hfov`` and
    its horizontal distance from the camera is within ``[depth_min, depth_max]``
    (nodepth mode: within ``depth_max``). Occlusion is not modeled."""
    cam = camera_position(pose, params)
    dx = float(mu[0]) - cam[0]
    dy = float(mu[1]) - cam[1]
    r = math.hypot(dx, dy)
    lo = params.depth_min if params.camera_mode == "depth" else 0.0
    if r < lo or r > params.depth_max:
        return False
    if r < 1e-9:
        return False
    da = wrap_angle(math.atan2(dy, dx) - (pose.yaw + params.cam_yaw))
    return abs(da) <= 0.5 * params.hfov


def make_in_view(params: Params) -> InView:
    """``in_view`` bound to ``params``, for ``MemoryAPI.update_frame``."""
    def _in_view(mu: np.ndarray, pose: Pose2D) -> bool:
        return in_view(mu, pose, params)
    return _in_view


# --------------------------------------------------------------- depth image
def median_depth(depth: Optional[np.ndarray], box: Box, frac: float = 0.3) -> Optional[float]:
    """Median of valid (> 0, finite) depth in the central ``frac`` of the box
    (``frac`` of its width and of its height). None when nothing is valid."""
    if depth is None:
        return None
    h, w = depth.shape[:2]
    left, top, right, bottom = box
    cu, cv = 0.5 * (left + right), 0.5 * (top + bottom)
    hw = 0.5 * frac * abs(right - left)
    hh = 0.5 * frac * abs(bottom - top)
    x0 = int(max(0, math.floor(cu - hw)))
    x1 = int(min(w, max(math.ceil(cu + hw), math.floor(cu - hw) + 1)))
    y0 = int(max(0, math.floor(cv - hh)))
    y1 = int(min(h, max(math.ceil(cv + hh), math.floor(cv - hh) + 1)))
    if x1 <= x0 or y1 <= y0:
        return None
    patch = np.asarray(depth[y0:y1, x0:x1], dtype=np.float64)
    valid = patch[np.isfinite(patch) & (patch > 0)]
    if valid.size == 0:
        return None
    return float(np.median(valid))
