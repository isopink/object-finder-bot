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
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


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
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(os.path.join(ld08_dir, "launch", "ld08.launch.py")),
        ),
        Node(
            package="turtlebot3_node",
            executable="turtlebot3_ros",
            parameters=[param_file],
            arguments=["-i", usb_port],
            output="screen",
        ),
    ])
