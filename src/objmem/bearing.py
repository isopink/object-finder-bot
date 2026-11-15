"""Bearing-only helpers for the nodepth (C920) camera mode.

A bearing is the map-frame angle (rad) of the sight line from the robot
position (``pose.x``, ``pose.y``) to the object. Python 3.8 compatible; numpy only.
"""
import math
from typing import Optional, Tuple

import numpy as np

from objmem.types import Params, Pose2D

# Rays closer to parallel than this (|sin(angle between them)|) are not intersected.
MIN_SIN_ANGLE = math.sin(math.radians(3.0))


def wrap_angle(a: float) -> float:
    """Wrap an angle to [-pi, pi)."""
    return (a + math.pi) % (2.0 * math.pi) - math.pi


def ray_covariance(bearing: float, sigma_along: float, sigma_across: float) -> np.ndarray:
    """2x2 covariance with std ``sigma_along`` along the ray and ``sigma_across`` across it."""
    c, s = math.cos(bearing), math.sin(bearing)
    rot = np.array([[c, -s], [s, c]], dtype=float)
    diag = np.diag([sigma_along ** 2, sigma_across ** 2])
    return rot @ diag @ rot.T


def ray_gaussian(pose: Pose2D, bearing: float, params: Params) -> Tuple[np.ndarray, np.ndarray]:
    """Gaussian for a first bearing-only sighting.

    Mean: the point ``nominal_range`` meters from the robot along the bearing.
    Covariance: std ``sigma_range_nodepth`` along the ray and
    ``nominal_range * sigma_bearing`` across it.
    """
    r = float(params.nominal_range)
    mu = np.array([pose.x + r * math.cos(bearing), pose.y + r * math.sin(bearing)], dtype=float)
    cov = ray_covariance(bearing, float(params.sigma_range_nodepth), r * float(params.sigma_bearing))
    return mu, cov


def triangulate(pose1: Pose2D, bearing1: float, pose2: Pose2D, bearing2: float) -> Optional[np.ndarray]:
    """Intersect two sight lines. Returns the (2,) map point, or None when the rays
    are near-parallel or the intersection lies behind either robot position."""
    p1 = np.array([pose1.x, pose1.y], dtype=float)
    p2 = np.array([pose2.x, pose2.y], dtype=float)
    d1 = np.array([math.cos(bearing1), math.sin(bearing1)])
    d2 = np.array([math.cos(bearing2), math.sin(bearing2)])
    cross = d1[0] * d2[1] - d1[1] * d2[0]
    if abs(cross) < MIN_SIN_ANGLE:
        return None
    # Solve p1 + t1 d1 = p2 + t2 d2.
    diff = p2 - p1
    t1 = (diff[0] * d2[1] - diff[1] * d2[0]) / cross
    t2 = (diff[0] * d1[1] - diff[1] * d1[0]) / cross
    if t1 <= 0.0 or t2 <= 0.0:
        return None
    return p1 + t1 * d1
