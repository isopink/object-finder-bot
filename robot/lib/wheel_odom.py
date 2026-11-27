#!/usr/bin/env python3
"""Wheel odometry from /joint_states: publishes /odom and the TF odom -> base_footprint.

Why: the diff_drive_controller inside turtlebot3_ros (Foxy, binary) stops updating the
heading after a while although the wheels turn and /joint_states is right. Seen three times
on 2026-11-27 (18:06 session: pose and heading frozen; 00:10: heading +0.0 deg for a
+2.17 / -2.17 rad wheel turn = 29 deg), with odometry.use_imu false. The maps of that
evening were ruined by it, and AMCL and the four-command navigator need a heading.
This node integrates the wheel angles itself. robot_ld08.launch.py starts it and moves the
controller's output out of the way (odometry.publish_tf: false, its topic -> /odom_tb3).
OFB_WHEEL_ODOM=0 goes back to the controller's odometry.

  python3 robot/lib/wheel_odom.py [--radius 0.033] [--separation 0.287]

Python 3.8, rclpy. The math (integrate) has no ROS import and is tested on a PC.
"""
import argparse
import math
import sys

MAX_STEP_RAD = 3.0      # a wheel turning more than this between two messages (50 ms) is a glitch


def integrate(x, y, th, d_left, d_right, separation):
    """Advance the pose by the distances the two wheels rolled (meters). Midpoint rule."""
    ds = 0.5 * (d_left + d_right)
    dth = (d_right - d_left) / separation
    mid = th + 0.5 * dth
    x += ds * math.cos(mid)
    y += ds * math.sin(mid)
    th = (th + dth + math.pi) % (2.0 * math.pi) - math.pi
    return x, y, th, ds, dth


class WheelOdometry(object):
    """Pose from successive wheel angles (rad). update() returns (x, y, th, v, w) or None."""

    def __init__(self, radius=0.033, separation=0.287):
        self.radius, self.separation = float(radius), float(separation)
        self.x = self.y = self.th = 0.0
        self.last = None            # (left, right, t)
        self.glitches = 0

    def update(self, left, right, t):
        if self.last is None:
            self.last = (left, right, t)
            return self.x, self.y, self.th, 0.0, 0.0
        l0, r0, t0 = self.last
        dl, dr = left - l0, right - r0
        dt = t - t0
        if abs(dl) > MAX_STEP_RAD or abs(dr) > MAX_STEP_RAD or not (math.isfinite(dl) and math.isfinite(dr)):
            self.glitches += 1      # the OpenCR restarted or a value jumped: start again from here
            self.last = (left, right, t)
            return None
        self.last = (left, right, t)
        self.x, self.y, self.th, ds, dth = integrate(self.x, self.y, self.th,
                                                     dl * self.radius, dr * self.radius, self.separation)
        v = ds / dt if dt > 1e-4 else 0.0
        w = dth / dt if dt > 1e-4 else 0.0
        return self.x, self.y, self.th, v, w


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--radius", type=float, default=0.033)
    ap.add_argument("--separation", type=float, default=0.287)
    ap.add_argument("--frame", default="odom")
    ap.add_argument("--child", default="base_footprint")
    args, ros_args = ap.parse_known_args(argv)

    import rclpy
    from geometry_msgs.msg import TransformStamped
    from nav_msgs.msg import Odometry
    from sensor_msgs.msg import JointState
    import tf2_ros

    rclpy.init(args=[sys.argv[0]] + ros_args)
    node = rclpy.create_node("ofb_wheel_odom")
    pub = node.create_publisher(Odometry, "/odom", 10)
    tfb = tf2_ros.TransformBroadcaster(node)
    odo = WheelOdometry(args.radius, args.separation)
    idx = {}
    count = {"n": 0}

    def on_joints(m):
        if not idx:
            names = list(m.name)
            left = [i for i, n in enumerate(names) if "left" in n]
            right = [i for i, n in enumerate(names) if "right" in n]
            idx["l"] = left[0] if left else 0
            idx["r"] = right[0] if right else 1
            node.get_logger().info("wheels: left = {}, right = {}".format(
                names[idx["l"]] if names else idx["l"], names[idx["r"]] if names else idx["r"]))
        if len(m.position) <= max(idx["l"], idx["r"]):
            return
        stamp = m.header.stamp
        t = stamp.sec + stamp.nanosec * 1e-9
        if t <= 0.0:
            stamp = node.get_clock().now().to_msg()
            t = stamp.sec + stamp.nanosec * 1e-9
        res = odo.update(float(m.position[idx["l"]]), float(m.position[idx["r"]]), t)
        if res is None:
            node.get_logger().warn("wheel angle jump ignored (glitch {})".format(odo.glitches))
            return
        x, y, th, v, w = res
        qz, qw = math.sin(0.5 * th), math.cos(0.5 * th)
        o = Odometry()
        o.header.stamp = stamp
        o.header.frame_id = args.frame
        o.child_frame_id = args.child
        o.pose.pose.position.x, o.pose.pose.position.y = x, y
        o.pose.pose.orientation.z, o.pose.pose.orientation.w = qz, qw
        o.twist.twist.linear.x, o.twist.twist.angular.z = v, w
        for i, c in ((0, 0.01), (7, 0.01), (14, 1e6), (21, 1e6), (28, 1e6), (35, 0.03)):
            o.pose.covariance[i] = c
            o.twist.covariance[i] = c
        pub.publish(o)
        tr = TransformStamped()
        tr.header.stamp = stamp
        tr.header.frame_id = args.frame
        tr.child_frame_id = args.child
        tr.transform.translation.x, tr.transform.translation.y = x, y
        tr.transform.rotation.z, tr.transform.rotation.w = qz, qw
        tfb.sendTransform(tr)
        count["n"] += 1
        if count["n"] % 1200 == 0:     # every minute at 20 Hz
            node.get_logger().info("odom x {:.2f} y {:.2f} heading {:.1f} deg".format(x, y, math.degrees(th)))

    node.create_subscription(JointState, "/joint_states", on_joints, 20)
    node.get_logger().info("wheel odometry: radius {} m, separation {} m -> /odom, TF {} -> {}".format(
        args.radius, args.separation, args.frame, args.child))
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        try:
            rclpy.shutdown()
        except Exception:
            pass


if __name__ == "__main__":
    main()
