#!/usr/bin/env bash
# Run on the Waffle Pi (Raspberry Pi): starts the LiDAR, odometry, and motor driver.
set -eo pipefail
source "$(dirname "$0")/env.sh"
ros2 launch turtlebot3_bringup robot.launch.py
