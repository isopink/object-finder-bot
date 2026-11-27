"""TurtleBot3 bringup with the LDS-02 (ld08_driver) LiDAR.

The Foxy apt release of turtlebot3_bringup/robot.launch.py ignores LDS_MODEL
and always starts hlds_laser_publisher (the LDS-01 driver). With an LDS-02
that driver publishes nothing on /scan (seen in the classroom on 2026-11-18).
This file is robot.launch.py with ld08_driver in place of hlds_laser.
robot/bringup.sh uses it only when LDS_MODEL=LDS-02 and the installed
robot.launch.py does not mention LDS_MODEL.

Usage: ros2 launch robot/launch/robot_ld08.launch.py usb_port:=/dev/ttyACM0
"""
import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, ExecuteProcess, IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def lidar_actions(ld08_dir):
    """The LDS-02 driver, plus robot/lib/scan_filter.py when it has work to do.

    driver -> /scan_raw -> scan_filter.py -> /scan. The filter gives every scan the
    same number of beams (OFB_SCAN_BEAMS; slam_toolbox drops scans whose count
    differs from the first) and, with OFB_SCAN_MIN > 0, drops returns from the
    camera mast rods inside the robot. With both at 0 the driver publishes /scan
    directly, as before.
    """
    def _num(name, cast):
        try:
            return cast(float(os.environ.get(name, "0") or 0))
        except ValueError:
            return cast(0)

    scan_min = _num("OFB_SCAN_MIN", float)
    beams = _num("OFB_SCAN_BEAMS", int)
    rotate = _num("OFB_SCAN_ROTATE_DEG", float)
    if scan_min <= 0 and beams <= 0 and rotate == 0:
        return [IncludeLaunchDescription(
            PythonLaunchDescriptionSource(os.path.join(ld08_dir, "launch", "ld08.launch.py")))]
    here = os.path.dirname(os.path.abspath(__file__))
    filt = os.path.join(os.path.dirname(here), "lib", "scan_filter.py")
    return [
        # Same node as ld08_driver/launch/ld08.launch.py, with its output renamed.
        Node(package="ld08_driver", executable="ld08_driver", name="ld08_driver", output="screen",
             remappings=[("scan", "scan_raw"), ("/scan", "/scan_raw")]),
        ExecuteProcess(cmd=["python3", filt, "--min-range", str(scan_min), "--beams", str(beams),
                            "--rotate-deg", str(rotate)],
                       output="screen"),
    ]


def odom_param_file(param_file):
    """The turtlebot3_node parameter file, or a copy with odometry.use_imu: false.

    With use_imu: true the diff_drive_controller takes the heading from /imu. On
    2026-11-25 it kept the heading frozen after a turn (wheels +97.7 deg, /imu +91.7 deg,
    /odom 0 deg) while straight driving was recorded, so every SLAM map came out straight
    instead of L-shaped. `-p odometry.use_imu:=false` on the command line does not help:
    the file's diff_drive_controller section wins (checked with ros2 param get). A copy
    with use_imu: false gave /odom +91.6 deg for a 91.6 deg wheel turn.
    OFB_ODOM_IMU=0 selects the copy; the default (1) keeps the installed file.
    """
    if os.environ.get("OFB_ODOM_IMU", "1").strip() != "0":
        return param_file
    with open(param_file) as f:
        text = f.read()
    out = os.path.join("/tmp", "ofb_" + os.path.basename(param_file).replace(".yaml", "_noimu.yaml"))
    with open(out, "w") as f:
        f.write(text.replace("use_imu: true", "use_imu: false"))
    return out


def generate_launch_description():
    model = os.environ.get("TURTLEBOT3_MODEL", "waffle_pi")
    usb_port = LaunchConfiguration("usb_port")
    bringup_dir = get_package_share_directory("turtlebot3_bringup")
    ld08_dir = get_package_share_directory("ld08_driver")
    param_file = os.path.join(bringup_dir, "param", model + ".yaml")

    return LaunchDescription([
        DeclareLaunchArgument("usb_port", default_value="/dev/ttyACM0",
                              description="OpenCR serial port"),
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(
                os.path.join(bringup_dir, "launch", "turtlebot3_state_publisher.launch.py")),
            launch_arguments={"use_sim_time": "false"}.items(),
        ),
    ] + lidar_actions(ld08_dir) + [
        Node(
            package="turtlebot3_node",
            executable="turtlebot3_ros",
            parameters=[odom_param_file(param_file)],
            arguments=["-i", usb_port],
            output="screen",
        ),
    ])
