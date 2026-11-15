#!/usr/bin/env bash
# Stop everything start_all.sh started: stop the wheels, Ctrl+C every pane
# (nodes save the memory file on shutdown), then close the tmux session.
#
# Usage: ./robot/stop_all.sh [--docker]   --docker also removes the Humble container
set -uo pipefail
source "$(dirname "$0")/env.sh"
SESSION="${OFB_TMUX_SESSION:-ofb}"

echo "== Stop the wheels"
if [ "$OFB_ROS_MODE" = native ] || [ "$OFB_ROS_MODE" = docker ]; then
  timeout 15 "$OFB_ROBOT_DIR/lib/ros_exec.sh" ros2 topic pub --once /cmd_vel geometry_msgs/msg/Twist "{}" >/dev/null 2>&1 \
    && echo "  [OK]   zero /cmd_vel sent" || echo "  [..]   could not publish /cmd_vel (bringup not running?)"
fi

if tmux has-session -t "$SESSION" 2>/dev/null; then
  echo "== Ctrl+C to every pane in '$SESSION'"
  for p in $(tmux list-panes -s -t "$SESSION" -F '#{pane_id}'); do tmux send-keys -t "$p" C-c; done
  sleep 5
  for p in $(tmux list-panes -s -t "$SESSION" -F '#{pane_id}' 2>/dev/null); do tmux send-keys -t "$p" C-c; done
  sleep 3
  tmux kill-session -t "$SESSION" 2>/dev/null && echo "  [OK]   tmux session '$SESSION' closed"
else
  echo "  [..]   no tmux session '$SESSION'"
fi

# Leftovers (a pane closed by hand, a crashed launch).
LEFT="$(pgrep -fa 'turtlebot3_ros|amcl|bt_navigator|controller_server|planner_server|map_server|vision_worker.py|objmem_ros' 2>/dev/null | grep -v pgrep || true)"
if [ -n "$LEFT" ]; then
  echo "  [..]   still running:"; echo "$LEFT" | sed 's/^/         /'
  echo "         stop them with: pkill -INT -f '<name>'  (in Docker mode: ./robot/docker/run.sh stop)"
else
  echo "  [OK]   no robot processes left"
fi
if [ "${1:-}" = "--docker" ]; then "$OFB_ROBOT_DIR/docker/run.sh" stop; fi
