"""A fake Nav2 `navigate_to_pose` action server for tests and dry runs.

    ros2 run objmem_ros fake_nav2 [--delay 0.5] [--fail 0]

Accepts every goal, waits `--delay` seconds, and succeeds (or aborts the
first `--fail` goals). Each goal is logged and published on
/fake_nav2/goals as "x y yaw".
"""
import argparse
import sys
import time


def main(argv=None):
    import rclpy
    from rclpy.action import ActionServer, CancelResponse, GoalResponse
    from rclpy.callback_groups import ReentrantCallbackGroup
    from rclpy.executors import MultiThreadedExecutor
    from rclpy.node import Node
    from std_msgs.msg import String
    from nav2_msgs.action import NavigateToPose

    from objmem_ros.core import yaw_from_quaternion

    argv = sys.argv[1:] if argv is None else argv
    ap = argparse.ArgumentParser(prog="fake_nav2")
    ap.add_argument("--delay", type=float, default=0.5)
    ap.add_argument("--fail", type=int, default=0, help="abort this many goals first")
    ap.add_argument("--action", default="navigate_to_pose")
    args, ros_args = ap.parse_known_args(argv)

    rclpy.init(args=[sys.argv[0]] + ros_args)
    node = Node("fake_nav2")
    pub = node.create_publisher(String, "/fake_nav2/goals", 10)
    state = {"n": 0}

    def execute(handle):
        state["n"] += 1
        p = handle.request.pose.pose
        yaw = yaw_from_quaternion(p.orientation.x, p.orientation.y, p.orientation.z, p.orientation.w)
        text = "{:.2f} {:.2f} {:.2f}".format(p.position.x, p.position.y, yaw)
        node.get_logger().info("goal #{}: {}".format(state["n"], text))
        msg = String()
        msg.data = text
        pub.publish(msg)
        t_end = time.time() + args.delay
        while time.time() < t_end:
            if handle.is_cancel_requested:
                handle.canceled()
                return NavigateToPose.Result()
            time.sleep(0.05)
        if state["n"] <= args.fail:
            handle.abort()
        else:
            handle.succeed()
        return NavigateToPose.Result()

    ActionServer(node, NavigateToPose, args.action, execute_callback=execute,
                 goal_callback=lambda _g: GoalResponse.ACCEPT,
                 cancel_callback=lambda _g: CancelResponse.ACCEPT,
                 callback_group=ReentrantCallbackGroup())
    node.get_logger().info("fake {} ready".format(args.action))
    ex = MultiThreadedExecutor()
    ex.add_node(node)
    try:
        ex.spin()
    except KeyboardInterrupt:
        pass
    except Exception as exc:
        if type(exc).__name__ != "ExternalShutdownException":
            raise
    finally:
        node.destroy_node()
        try:
            rclpy.shutdown()
        except Exception:
            pass


if __name__ == "__main__":
    main()
