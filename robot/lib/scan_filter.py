#!/usr/bin/env python3
"""Clean up the LDS-02 scan on its way to SLAM, AMCL and Nav2.

  /scan_raw (ld08_driver) -> scan_filter.py -> /scan

Two independent jobs (both off when their value is 0):

--beams N       Send exactly N beams per scan. The driver's count changes from scan
                to scan (242 to 249) and slam_toolbox throws away every scan whose
                count differs from the first one (about 60 % on 2026-11-25).
                See robot/lib/scan_resample.py.
--min-range M   Drop returns closer than M meters (camera mast rods inside the
                scan plane): they become +inf ("no return") and range_min is raised.
                On 2026-11-25 the LiDAR did not see the rods at all (nothing
                closer than 0.42 m in 60 scans), so this stays off unless needed.

robot/launch/robot_ld08.launch.py starts this node when OFB_SCAN_BEAMS > 0 or
OFB_SCAN_MIN > 0 (OFB_SCAN_BEAMS defaults to 240 in robot/env.sh).

Python 3.8, system rclpy (no conda).
"""
import argparse
import math
import os
import sys

import rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import LaserScan

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from scan_resample import resample_ranges  # noqa: E402


class ScanFilter(Node):
    def __init__(self, min_range, beams, in_topic, out_topic):
        super().__init__("ofb_scan_filter")
        self.min_range = float(min_range)
        self.beams = int(beams)
        self.n = 0
        self.pub = self.create_publisher(LaserScan, out_topic, qos_profile_sensor_data)
        self.sub = self.create_subscription(LaserScan, in_topic, self.cb, qos_profile_sensor_data)
        self.get_logger().info("%s -> %s, beams %s, dropping returns closer than %.2f m"
                               % (in_topic, out_topic, self.beams or "unchanged", self.min_range))

    def cb(self, msg):
        dropped = 0
        ranges = list(msg.ranges)
        if self.beams > 0:
            ranges, inc = resample_ranges(ranges, msg.angle_min, msg.angle_increment, self.beams)
            msg.angle_increment = inc
            msg.angle_max = msg.angle_min + (self.beams - 1) * inc
            msg.intensities = []
        if self.min_range > 0:
            inf = float("inf")
            for i, r in enumerate(ranges):
                if not math.isinf(r) and not math.isnan(r) and r < self.min_range:
                    ranges[i] = inf
                    dropped += 1
            msg.range_min = max(float(msg.range_min), self.min_range)
        msg.ranges = ranges
        self.pub.publish(msg)
        self.n += 1
        if self.n == 1 or self.n % 300 == 0:  # about every minute at 5 Hz
            self.get_logger().info("scan %d: %d beams, dropped %d returns (< %.2f m)"
                                   % (self.n, len(ranges), dropped, self.min_range))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-range", type=float, default=0.0)
    ap.add_argument("--beams", type=int, default=0)
    ap.add_argument("--in", dest="in_topic", default="/scan_raw")
    ap.add_argument("--out", dest="out_topic", default="/scan")
    args, _ = ap.parse_known_args(argv)
    rclpy.init()
    node = ScanFilter(args.min_range, args.beams, args.in_topic, args.out_topic)
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    node.destroy_node()
    rclpy.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
