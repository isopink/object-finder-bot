#!/usr/bin/env bash
# Drive the robot from the keyboard over SSH (bringup.sh must be running).
# Keys: w/x faster/slower forward, a/d turn, s or space stop, Ctrl+C quit.
# Drive slowly: the raised camera mast makes the robot top-heavy.
#
# Usage: ./robot/teleop.sh
set -uo pipefail
source "$(dirname "$0")/env.sh"
ofb_need_ros "$0" "$@"
# No tee: the teleop node needs the real terminal for key presses.
ofb_log_init teleop --no-tee

if ! [ -t 0 ]; then
  echo "[FAIL] teleop needs an interactive terminal" | tee -a "$OFB_LOG_FILE"
  echo "       hint: run it directly in an SSH session or a tmux pane, not through a pipe"
  exit 1
fi
if ! ofb_wait_topic /odom 5; then
  echo "[FAIL] no /odom: the robot is not up" | tee -a "$OFB_LOG_FILE"
  echo "       hint: start ./robot/bringup.sh in another tmux pane first"
  exit 1
fi
echo "[OK]   /odom is alive; starting teleop_keyboard" | tee -a "$OFB_LOG_FILE"
ros2 run turtlebot3_teleop teleop_keyboard
echo "== teleop ended $(date '+%H:%M:%S')" >> "$OFB_LOG_FILE"
# Make sure the robot does not keep the last command.
timeout 5 ros2 topic pub --once /cmd_vel geometry_msgs/msg/Twist "{}" >/dev/null 2>&1 || true
