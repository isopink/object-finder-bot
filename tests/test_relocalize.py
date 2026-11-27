"""robot/lib/relocalize.py: find the robot pose from one scan and the map, without a first guess."""
import math
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "robot", "lib"))
import relocalize as rl  # noqa: E402

RES = 0.05
ORIGIN = (-2.0, -3.0)


def room():
    """8 x 5 m room, not symmetric: a pillar and a short inner wall."""
    occ = np.zeros((100, 160), bool)
    occ[0, :] = occ[-1, :] = True
    occ[:, 0] = occ[:, -1] = True
    occ[30:36, 50:56] = True            # pillar
    occ[60, 90:140] = True              # inner wall
    occ[20:45, 120] = True              # another wall
    return occ


def scan_from(occ, x, y, yaw, beams=240, r_max=6.0):
    """Ranges a LiDAR at base_link + LIDAR_X would measure (ray marching, 1 cm steps)."""
    lx, ly = x + rl.LIDAR_X * math.cos(yaw), y + rl.LIDAR_X * math.sin(yaw)
    out = []
    for i in range(beams):
        a = yaw + 2 * math.pi * i / beams
        r = float("inf")
        for step in range(1, int(r_max / 0.01)):
            d = step * 0.01
            ix = int((lx + d * math.cos(a) - ORIGIN[0]) / RES)
            iy = int((ly + d * math.sin(a) - ORIGIN[1]) / RES)
            if not (0 <= ix < occ.shape[1] and 0 <= iy < occ.shape[0]):
                break
            if occ[iy, ix]:
                r = d
                break
        out.append(r)
    return out


@pytest.mark.parametrize("pose", [(1.0, -1.0, 0.3), (4.2, 0.6, -2.0), (0.3, 1.2, 3.0)])
def test_locate_finds_the_pose_without_a_first_guess(pose):
    occ = room()
    field = rl.wall_field(occ)
    pts = rl.scan_points(scan_from(occ, *pose), 0.0, 2 * math.pi / 240)
    sc, x, y, yaw = rl.locate(field, RES, ORIGIN, pts, occ=occ)
    assert sc > 0.8
    assert math.hypot(x - pose[0], y - pose[1]) < 0.10
    assert abs((yaw - pose[2] + math.pi) % (2 * math.pi) - math.pi) < math.radians(3)


def test_wrong_pose_scores_much_lower_than_the_true_one():
    occ = room()
    field = rl.wall_field(occ)
    pts = rl.scan_points(scan_from(occ, 1.0, -1.0, 0.3), 0.0, 2 * math.pi / 240)
    good = rl.score(field, RES, ORIGIN, pts, 1.0, -1.0, 0.3)
    bad = rl.score(field, RES, ORIGIN, pts, 2.8, -1.4, 0.0)      # 1.8 m off, like AMCL on 2026-11-27
    assert good > 0.85 and bad < 0.6 * good


def test_scan_points_drop_bad_returns_and_apply_the_lidar_offset():
    pts = rl.scan_points([1.0, float("inf"), float("nan"), 0.05, 9.0, 2.0], 0.0, math.pi / 2)
    assert len(pts) == 2
    assert pts[0] == pytest.approx([1.0 + rl.LIDAR_X, 0.0])


def test_beams_through_walls_tell_similar_places_apart():
    occ = room()
    pts = rl.scan_points(scan_from(occ, 4.2, 0.6, -2.0), 0.0, 2 * math.pi / 240)
    assert rl.crossing(occ, RES, ORIGIN, pts, 4.2, 0.6, -2.0) < 0.05         # the true pose: none
    assert rl.crossing(occ, RES, ORIGIN, pts, 4.6, -1.275, -2.0) > 0.15      # the look-alike across the wall
