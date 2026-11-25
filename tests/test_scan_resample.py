"""robot/lib/scan_resample.py: every LaserScan gets the same number of beams."""
import importlib.util
import math
import os

_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "robot", "lib", "scan_resample.py")
_spec = importlib.util.spec_from_file_location("scan_resample", _PATH)
scan_resample = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(scan_resample)
resample_ranges = scan_resample.resample_ranges

INC = math.radians(1.46)   # about what the LDS-02 driver sends: 242-249 beams per turn


def test_any_driver_count_becomes_exactly_n():
    for m in range(242, 250):
        out, inc = resample_ranges([1.0] * m, 0.02, INC, 240)
        assert len(out) == 240
        assert abs(inc - 2 * math.pi / 240) < 1e-12


def test_values_follow_the_angle():
    ranges = [float(i) for i in range(246)]            # range = beam index
    out, inc = resample_ranges(ranges, 0.0, INC, 240)
    assert out[0] == 0.0
    for j in (10, 60, 120, 200):                      # nearest original beam at the same angle
        assert abs(out[j] - round(j * inc / INC)) < 1e-9
    assert all(a <= b for a, b in zip(out, out[1:]))  # no reordering


def test_end_is_clamped_to_the_last_beam():
    ranges = [float(i) for i in range(242)]
    out, _ = resample_ranges(ranges, 0.0, INC, 240)
    assert out[-1] <= 241.0                           # index never runs past the input


def test_invalid_values_are_kept():
    ranges = [1.0] * 246
    ranges[100] = float("inf")
    ranges[101] = float("nan")
    out, _ = resample_ranges(ranges, 0.0, INC, 240)
    assert any(math.isinf(x) for x in out) and any(math.isnan(x) for x in out)


def test_off_or_empty_leaves_the_scan_alone():
    assert resample_ranges([1.0, 2.0], 0.0, INC, 0) == ([1.0, 2.0], INC)
    assert resample_ranges([], 0.0, INC, 240) == ([], INC)
    assert resample_ranges([1.0], 0.0, 0.0, 240) == ([1.0], 0.0)
