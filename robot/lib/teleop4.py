#!/usr/bin/env python3
"""Four-key teleop for mapping: straight, turn right 90, turn left 90, stop.

  w  go straight at a fixed slow speed until you press s (or something is in front)
  d  turn right 90 degrees in place (uses /odom yaw feedback, stops by itself)
  a  turn left 90 degrees in place
  s  stop now (space also works). q quits (and stops).

Why: the stock teleop changes speeds in steps and a turn is easy to overshoot, which
spoils SLAM. Fixed slow speeds and exact 90 degree turns keep the map clean.
The robot stops by itself when /odom or /scan stop arriving, or when something is closer
than --stop-dist in front (LiDAR 0 degrees, the direction w drives).
Env: OFB_T4_SPEED (m/s, default 0.08), OFB_T4_TURN (rad/s, default 0.25).
"""
import math
import os
import select
import sys
import termios
import time
import tty

import rclpy
from geometry_msgs.msg import Twist
from nav_msgs.msg import Odometry
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import LaserScan


def wrap(a):
    return (a + math.pi) % (2 * math.pi) - math.pi


def main():
    speed = float(os.environ.get("OFB_T4_SPEED", "0.08"))
    turn = float(os.environ.get("OFB_T4_TURN", "0.25"))
    stop_dist = 0.30
    rclpy.init()
    n = rclpy.create_node("ofb_teleop4")
    pub = n.create_publisher(Twist, "/cmd_vel", 10)
    st = {"yaw": None, "t_odom": 0.0, "front": 9.9, "t_scan": 0.0}

    def on_odom(m):
        q = m.pose.pose.orientation
        st["yaw"] = math.atan2(2 * (q.w * q.z + q.x * q.y), 1 - 2 * (q.y * q.y + q.z * q.z))
        st["t_odom"] = time.time()

    def on_scan(m):
        vals = []
        for i, r in enumerate(m.ranges):
            a = math.degrees(m.angle_min + i * m.angle_increment) % 360
            if (a <= 20 or a >= 340) and r == r and 0.05 < r < 20:
                vals.append(r)
        st["front"] = min(vals) if vals else 9.9
        st["t_scan"] = time.time()

    n.create_subscription(Odometry, "/odom", on_odom, 10)
    n.create_subscription(LaserScan, "/scan", on_scan, qos_profile_sensor_data)

    mode, target_acc, last_yaw = "stop", 0.0, None
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    tty.setcbreak(fd)

    def say(msg):
        sys.stdout.write("\r\033[K" + msg + "\r\n")
        sys.stdout.flush()

    say("w straight | d right 90 | a left 90 | s stop | q quit   (speed %.2f m/s, turn %.2f rad/s)" % (speed, turn))
    try:
        while rclpy.ok():
            rclpy.spin_once(n, timeout_sec=0.05)
            now = time.time()
            tw = Twist()
            alive = now - st["t_odom"] < 1.0 and now - st["t_scan"] < 1.0
            if mode != "stop" and not alive:
                mode = "stop"
                say("STOP: no /odom or /scan for 1 s")
            if r := select.select([sys.stdin], [], [], 0)[0]:
                k = sys.stdin.read(1).lower()
                if k in ("s", " "):
                    mode = "stop"; say("stop")
                elif k == "q":
                    break
                elif k == "w" and alive:
                    mode = "fwd"; say("straight")
                elif k in ("a", "d") and alive and st["yaw"] is not None:
                    mode = "left" if k == "a" else "right"
                    target_acc, last_yaw = 0.0, st["yaw"]
                    say("turning %s 90" % ("left" if k == "a" else "right"))
                elif k in ("w", "a", "d"):
                    say("not now: no /odom or /scan")
            if mode == "fwd":
                if st["front"] < stop_dist:
                    mode = "stop"; say("STOP: something %.2f m in front" % st["front"])
                else:
                    tw.linear.x = speed
            elif mode in ("left", "right"):
                d = wrap(st["yaw"] - last_yaw); last_yaw = st["yaw"]
                target_acc += d
                sign = 1.0 if mode == "left" else -1.0
                done = sign * target_acc
                if done >= math.radians(88.0):          # 2 degrees of lead for the stopping delay
                    mode = "stop"; say("turned %.0f deg" % math.degrees(done))
                else:
                    tw.angular.z = sign * turn
            pub.publish(tw)
    finally:
        for _ in range(10):
            pub.publish(Twist()); time.sleep(0.02)
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
        n.destroy_node(); rclpy.shutdown()


if __name__ == "__main__":
    main()
