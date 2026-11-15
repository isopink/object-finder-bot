#!/usr/bin/env bash
# Build a SLAM map with a simulated Waffle Pi in Gazebo.
# Usage: ./sim_slam.sh [cartographer|slam_toolbox] [world|house]
# Drive the robot from another terminal: ros2 run turtlebot3_teleop teleop_keyboard
set -eo pipefail
source "$(dirname "$0")/env.sh"

METHOD="${1:-slam_toolbox}"
WORLD="${2:-world}"

ros2 launch turtlebot3_gazebo "turtlebot3_${WORLD}.launch.py" &
GAZEBO_PID=$!
trap 'kill $GAZEBO_PID 2>/dev/null' EXIT
sleep 8

case "$METHOD" in
  cartographer)
    ros2 launch turtlebot3_cartographer cartographer.launch.py use_sim_time:=True
    ;;
  slam_toolbox)
    RVIZ="$(ros2 pkg prefix turtlebot3_cartographer)/share/turtlebot3_cartographer/rviz/tb3_cartographer.rviz"
    rviz2 -d "$RVIZ" --ros-args -p use_sim_time:=True &
    ros2 launch slam_toolbox online_async_launch.py use_sim_time:=True
    ;;
  *)
    echo "Unknown method: $METHOD (cartographer | slam_toolbox)" >&2
    exit 1
    ;;
esac
