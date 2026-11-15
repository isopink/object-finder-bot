import math

import numpy as np
import pytest

from objmem.bearing import ray_gaussian, triangulate, wrap_angle
from objmem.types import Params, Pose2D


def test_wrap_angle():
    assert wrap_angle(0.0) == pytest.approx(0.0)
    assert wrap_angle(3 * math.pi / 2) == pytest.approx(-math.pi / 2)
    assert wrap_angle(-3 * math.pi / 2) == pytest.approx(math.pi / 2)


def test_ray_gaussian_mean_and_elongated_cov():
    params = Params()
    pose = Pose2D(1.0, 2.0, 0.3)
    b = 0.7
    mu, cov = ray_gaussian(pose, b, params)
    r = params.nominal_range
    assert mu == pytest.approx([1.0 + r * math.cos(b), 2.0 + r * math.sin(b)])
    along = np.array([math.cos(b), math.sin(b)])
    across = np.array([-math.sin(b), math.cos(b)])
    assert along @ cov @ along == pytest.approx(params.sigma_range_nodepth ** 2)
    assert across @ cov @ across == pytest.approx((r * params.sigma_bearing) ** 2)
    assert along @ cov @ across == pytest.approx(0.0, abs=1e-12)
    vals, vecs = np.linalg.eigh(cov)
    assert abs(abs(vecs[:, -1] @ along) - 1.0) < 1e-9


def test_triangulate_recovers_point():
    target = np.array([2.0, 1.5])
    poses = [Pose2D(0.0, 0.0, 0.0), Pose2D(3.0, -1.0, 2.0), Pose2D(0.5, 3.0, -1.0)]
    for i in range(len(poses)):
        for j in range(i + 1, len(poses)):
            p1, p2 = poses[i], poses[j]
            b1 = math.atan2(target[1] - p1.y, target[0] - p1.x)
            b2 = math.atan2(target[1] - p2.y, target[0] - p2.x)
            got = triangulate(p1, b1, p2, b2)
            assert got is not None
            assert got == pytest.approx(target, abs=1e-9)


def test_triangulate_near_parallel_is_none():
    p1 = Pose2D(0.0, 0.0, 0.0)
    p2 = Pose2D(0.0, 0.1, 0.0)
    assert triangulate(p1, 0.0, p2, 0.0) is None
    assert triangulate(p1, 0.0, p2, 0.01) is None
    assert triangulate(p1, 0.0, p2, math.pi) is None


def test_triangulate_behind_is_none():
    # The lines cross at (2, 0), but behind the second robot.
    p1 = Pose2D(0.0, 0.0, 0.0)
    p2 = Pose2D(2.0, -1.0, 0.0)
    assert triangulate(p1, 0.0, p2, -math.pi / 2) is None
    assert triangulate(p1, 0.0, p2, math.pi / 2) == pytest.approx([2.0, 0.0])
