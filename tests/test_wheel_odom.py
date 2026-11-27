"""robot/lib/wheel_odom.py: wheel odometry math."""
import math
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "robot", "lib"))
import wheel_odom as wo  # noqa: E402

R, SEP = 0.033, 0.287


def test_turn_in_place_from_the_measured_wheel_angles():
    # 2026-11-28 00:10: left -2.17 rad, right +2.17 rad; the controller reported +0.0 deg
    o = wo.WheelOdometry(R, SEP)
    o.update(0.0, 0.0, 0.0)
    for k in range(1, 41):                      # 2 s at 20 Hz
        x, y, th, v, w = o.update(-2.17 * k / 40, 2.17 * k / 40, k * 0.05)
    assert math.degrees(th) == pytest.approx(math.degrees(2 * 2.17 * R / SEP), abs=0.01)   # 28.5 deg, left
    assert math.hypot(x, y) < 1e-9 and w > 0


def drive(o, left_to, right_to, t0, steps=200, dt=0.05):
    l0, r0, _ = o.last
    res = None
    for k in range(1, steps + 1):
        res = o.update(l0 + (left_to - l0) * k / steps, r0 + (right_to - r0) * k / steps, t0 + k * dt)
        assert res is not None
    return res


def test_straight_and_an_l_shape():
    o = wo.WheelOdometry(R, SEP)
    o.update(0.0, 0.0, 0.0)
    one_m = 1.0 / R
    x, y, th, v, _ = drive(o, one_m, one_m, 0.0)
    assert (x, y, th) == pytest.approx((1.0, 0.0, 0.0))
    quarter = (math.pi / 2) * SEP / 2 / R       # wheel angle for a 90 degree turn in place
    drive(o, one_m - quarter, one_m + quarter, 10.0)
    x, y, th, _, _ = drive(o, 2 * one_m - quarter, 2 * one_m + quarter, 20.0)
    assert th == pytest.approx(math.pi / 2) and x == pytest.approx(1.0) and y == pytest.approx(1.0)


def test_a_jump_is_ignored_and_tracking_goes_on():
    o = wo.WheelOdometry(R, SEP)
    o.update(5.0, 5.0, 0.0)
    assert o.update(500.0, 5.0, 0.05) is None and o.glitches == 1     # e.g. OpenCR restarted
    x, y, th, _, _ = o.update(501.0, 6.0, 0.10)                       # continues from the new values
    assert th == pytest.approx(0.0) and x == pytest.approx(R)
    assert o.update(float("nan"), 6.0, 0.15) is None


def test_backwards_and_turning_right_are_negative():
    o = wo.WheelOdometry(R, SEP)
    o.update(0.0, 0.0, 0.0)
    x, _, _, v, _ = o.update(-1.0, -1.0, 1.0)
    assert x == pytest.approx(-R) and v < 0
    _, _, th, _, w = o.update(-0.5, -1.5, 2.0)
    assert th < 0 and w < 0
