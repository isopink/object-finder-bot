#!/usr/bin/env python3
"""Print the robot pose from TF as "x y yaw" (meters, radians).

Usage: python3 robot/lib/ros_pose.py [--parent map] [--child base_link] [--timeout 10]

Works on Foxy and Humble (rclpy + tf2_ros). Exit status 1 if the transform
does not arrive within the timeout. Python 3.8 syntax.
"""
import argparse
import math
import sys
import time


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--parent", default="map")
    ap.add_argument("--child", default="base_link")
    ap.add_argument("--timeout", type=float, default=10.0)
    args = ap.parse_args()

    import rclpy
    from rclpy.duration import Duration
    from rclpy.time import Time
    from tf2_ros import Buffer, TransformListener

    rclpy.init()
    node = rclpy.create_node("ofb_pose_probe")
    buf = Buffer()
    TransformListener(buf, node)
    deadline = time.time() + args.timeout
    tf = None
    while time.time() < deadline:
        rclpy.spin_once(node, timeout_sec=0.2)
        try:
            tf = buf.lookup_transform(args.parent, args.child, Time(), timeout=Duration(seconds=0.0))
            break
        except Exception:  # noqa: BLE001 (tf2 raises several exception types)
            continue
    node.destroy_node()
    rclpy.shutdown()
    if tf is None:
        sys.stderr.write("no transform %s -> %s within %.0f s\n" % (args.parent, args.child, args.timeout))
        return 1
    t = tf.transform.translation
    q = tf.transform.rotation
    yaw = math.atan2(2.0 * (q.w * q.z + q.x * q.y), 1.0 - 2.0 * (q.y * q.y + q.z * q.z))
    print("%.3f %.3f %.3f" % (t.x, t.y, yaw))
    return 0


if __name__ == "__main__":
    sys.exit(main())
