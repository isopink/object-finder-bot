"""Give every LaserScan the same number of beams (pure Python, no ROS).

The LDS-02 driver (ld08_driver) sends 242 to 249 ranges per revolution; on
2026-11-25 about 60 % of the scans had a different count from the first one.
slam_toolbox fixes the beam count on the first scan ("LaserRangeScan contains 245
range readings, expected 246") and throws every scan that differs away, so the map
was built from a third of the data. resample_ranges() turns each scan into one
full circle of exactly n beams (nearest beam), which slam_toolbox accepts.
"""
import math


def resample_ranges(ranges, angle_min, angle_increment, n):
    """Return (new_ranges, new_increment): n beams over 2*pi starting at angle_min.

    Beam j looks at angle_min + j * (2*pi / n); its value is the range of the nearest
    original beam (clamped to the first/last one at the ends).
    """
    m = len(ranges)
    if n <= 0 or m == 0 or angle_increment == 0:
        return list(ranges), angle_increment
    new_inc = 2.0 * math.pi / n
    out = []
    for j in range(n):
        i = int(round(j * new_inc / angle_increment))
        out.append(ranges[min(max(i, 0), m - 1)])
    return out, new_inc
