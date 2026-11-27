"""ROS 2 node: a NavigateToPose action server that drives with four commands only.

    ros2 run objmem_ros gridnav [--ros-args -p speed:=0.08 -p turn_rate:=0.25 -p radius:=0.20]

Serves the action `navigate_to_pose_4cmd` (same type as Nav2's, so the finder only needs
`nav_action:=navigate_to_pose_4cmd`). Nav2 (map_server + AMCL) keeps running for the
localisation; its planner and controller are not used.
Needs: the aisle map (-p map_yaml:=<name>_nav.yaml; without it the /map topic is used),
TF map -> base_link (AMCL on the full SLAM map), /scan (front stop); publishes /cmd_vel.
Planning and driving logic: gridnav.py (tested on a PC with a simulated robot).
"""
import math
import sys
import threading
import time


def main(argv=None):
    import rclpy
    from geometry_msgs.msg import Twist
    from nav2_msgs.action import NavigateToPose
    from nav_msgs.msg import OccupancyGrid
    from rclpy.action import ActionServer, CancelResponse, GoalResponse
    from rclpy.callback_groups import ReentrantCallbackGroup
    from rclpy.executors import MultiThreadedExecutor
    from rclpy.node import Node
    from rclpy.qos import QoSProfile, DurabilityPolicy, ReliabilityPolicy, qos_profile_sensor_data
    from sensor_msgs.msg import LaserScan

    from objmem_ros import core, gridnav
    from objmem_ros.nodes import TfPose

    rclpy.init(args=sys.argv[1:] if argv is None else argv)
    node = Node("gridnav")

    def param(name, default):
        node.declare_parameter(name, default)
        return type(default)(node.get_parameter(name).value)

    action_name = param("action_name", "navigate_to_pose_4cmd")
    speed = param("speed", 0.08)
    turn_rate = param("turn_rate", 0.25)
    radius = param("radius", 0.20)
    front_stop = param("front_stop", 0.30)
    goal_tol = param("goal_tol", 0.15)
    max_time = param("max_time_s", 220.0)
    map_yaml = param("map_yaml", "")
    log = node.get_logger()

    pub = node.create_publisher(Twist, "/cmd_vel", 10)
    tf = TfPose(node)
    state = {"grid": None, "front": 9.9, "t_scan": 0.0}

    def on_map(m):
        state["grid"] = gridnav.grid_from_occupancy(m.data, m.info.width, m.info.height, m.info.resolution,
                                                    (m.info.origin.position.x, m.info.origin.position.y), radius)
        log.info("map {}x{} cells, {:.2f} m/cell, free after the {:.2f} m robot radius: {:.1f} m2".format(
            m.info.width, m.info.height, m.info.resolution, radius,
            float(state["grid"].free.sum()) * m.info.resolution ** 2))

    def on_scan(m):
        vals = []
        for i, r in enumerate(m.ranges):
            a = math.degrees(m.angle_min + i * m.angle_increment) % 360.0
            if (a <= 20.0 or a >= 340.0) and r == r and 0.05 < r < 20.0:
                vals.append(r)
        state["front"] = min(vals) if vals else 9.9
        state["t_scan"] = time.time()

    if map_yaml:
        state["grid"] = gridnav.grid_from_map_file(map_yaml, radius)
        g = state["grid"]
        log.info("aisle map {}: {}x{} cells, {:.2f} m/cell, free after the {:.2f} m robot radius: {:.1f} m2".format(
            map_yaml, g.free.shape[1], g.free.shape[0], g.res, radius, float(g.free.sum()) * g.res ** 2))
    else:
        node.create_subscription(OccupancyGrid, "/map", on_map,
                                 QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL,
                                            reliability=ReliabilityPolicy.RELIABLE))
    node.create_subscription(LaserScan, "/scan", on_scan, qos_profile_sensor_data)

    busy = threading.Lock()

    class RosIO(object):
        def __init__(self, handle):
            self.handle = handle

        def pose(self):
            p = tf.lookup()
            return None if p is None else (p.x, p.y, p.yaw)

        def cmd(self, v, w):
            t = Twist()
            t.linear.x, t.angular.z = float(v), float(w)
            pub.publish(t)

        def front(self):
            # no scan for a second: treat as blocked, never drive blind
            return state["front"] if time.time() - state["t_scan"] < 1.0 else 0.0

        def now(self):
            return time.time()

        def sleep(self, s):
            time.sleep(s)

        def cancelled(self):
            return self.handle.is_cancel_requested

        def log(self, text):
            log.info(text)

    def execute(handle):
        result = NavigateToPose.Result()
        if state["grid"] is None:
            log.error("no /map yet: is the Nav2 map_server running?")
            handle.abort()
            return result
        if not busy.acquire(blocking=False):
            log.warn("a goal is already running")
            handle.abort()
            return result
        try:
            p = handle.request.pose.pose
            yaw = core.yaw_from_quaternion(p.orientation.x, p.orientation.y, p.orientation.z, p.orientation.w)
            log.info("goal: x {:.2f} y {:.2f} yaw {:.2f}".format(p.position.x, p.position.y, yaw))
            io = RosIO(handle)
            runner = gridnav.Runner(io, lambda: state["grid"], speed=speed, turn_rate=turn_rate,
                                    front_stop=front_stop, goal_tol=goal_tol)
            status = runner.go((p.position.x, p.position.y), yaw, max_time_s=max_time)
            runner.stop()
            log.info("goal finished: {}".format(status))
            if status == "stuck":
                log.error("the pose did not change while the robot was told to move: odometry frozen "
                          "(restart bringup.sh) or the motors are off (battery, OpenCR)")
            if status == "ok":
                handle.succeed()
            elif status == "cancel":
                handle.canceled()
            else:
                handle.abort()
        finally:
            busy.release()
        return result

    ActionServer(node, NavigateToPose, action_name, execute_callback=execute,
                 goal_callback=lambda _g: GoalResponse.ACCEPT,
                 cancel_callback=lambda _g: CancelResponse.ACCEPT,
                 callback_group=ReentrantCallbackGroup())
    log.info("{} ready: straight {:.2f} m/s, turns {:.2f} rad/s, front stop {:.2f} m".format(
        action_name, speed, turn_rate, front_stop))
    ex = MultiThreadedExecutor(num_threads=4)
    ex.add_node(node)
    try:
        ex.spin()
    except KeyboardInterrupt:
        pass
    except Exception as exc:
        if type(exc).__name__ != "ExternalShutdownException":
            raise
    finally:
        try:
            pub.publish(Twist())
        except Exception:
            pass
        node.destroy_node()
        try:
            rclpy.shutdown()
        except Exception:
            pass


if __name__ == "__main__":
    main()
