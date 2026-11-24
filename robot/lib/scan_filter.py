#!/usr/bin/env python3
"""Drop LiDAR returns from parts of the robot itself (camera mast rods).

The camera mast stands inside the LiDAR's scan plane, so the LiDAR sees its
rods as two obstacles that move with the robot: Nav2 then thinks the robot is
always in collision and SLAM gets ghost points. Everything the LiDAR sees closer
than --min-range (meters) is inside the robot body, so this node replaces those
ranges with +inf ("no return") and raises range_min to match.

  /scan_raw (driver) -> scan_filter.py -> /scan (SLAM, AMCL, Nav2)

robot/launch/robot_ld08.launch.py starts it when OFB_SCAN_MIN > 0, e.g.
  OFB_SCAN_MIN=0.20 ./robot/bringup.sh
Pick a value a little larger than the farthest rod's distance from the LiDAR
center and smaller than the distance to the robot's outer edge.

Python 3.8, system rclpy (no conda).
"""
import argparse
import math
import sys

import rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import LaserScan


class ScanFilter(Node):
    def __init__(self, min_range, in_topic, out_topic):
        super().__init__("ofb_scan_filter")
        self.min_range = float(min_range)
        self.n = 0
        self.pub = self.create_publisher(LaserScan, out_topic, qos_profile_sensor_data)
        self.sub = self.create_subscription(LaserScan, in_topic, self.cb, qos_profile_sensor_data)
        self.get_logger().info("%s -> %s, dropping returns closer than %.2f m"
                               % (in_topic, out_topic, self.min_range))

    def cb(self, msg):
        inf = float("inf")
        dropped = 0
        ranges = list(msg.ranges)
        for i, r in enumerate(ranges):
            if not math.isinf(r) and not math.isnan(r) and r < self.min_range:
                ranges[i] = inf
                dropped += 1
        msg.ranges = ranges
        msg.range_min = max(float(msg.range_min), self.min_range)
        self.pub.publish(msg)
        self.n += 1
        if self.n == 1 or self.n % 300 == 0:  # about every minute at 5 Hz
            self.get_logger().info("scan %d: dropped %d of %d returns (< %.2f m)"
                                   % (self.n, dropped, len(ranges), self.min_range))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-range", type=float, default=0.20)
    ap.add_argument("--in", dest="in_topic", default="/scan_raw")
    ap.add_argument("--out", dest="out_topic", default="/scan")
    args, _ = ap.parse_known_args(argv)
    rclpy.init()
    node = ScanFilter(args.min_range, args.in_topic, args.out_topic)
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    node.destroy_node()
    rclpy.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
