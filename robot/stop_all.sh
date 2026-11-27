#!/usr/bin/env bash
# Stop everything start_all.sh started: stop the wheels, Ctrl+C every pane
# (nodes save the memory file on shutdown), then close the tmux session.
#
# Usage: ./robot/stop_all.sh [--keep-worker] [--docker]
#   --keep-worker  leave the vision worker (and its tmux pane) running. Use this for every
#                  restart on the Jetson: after the worker has been stopped once, the GPU often
#                  cannot give the NanoOWL engine its memory again ("Engine deserialization
#                  failed", 2026-11-27, twice in a row) and only a reboot helps.
#                  start_all.sh then reuses the running worker.
#   --docker       also removes the Humble container
set -uo pipefail
source "$(dirname "$0")/env.sh"
SESSION="${OFB_TMUX_SESSION:-ofb}"
KEEP=0; DOCKER=0
for a in "$@"; do
  case "$a" in --keep-worker) KEEP=1 ;; --docker) DOCKER=1 ;; *) echo "usage: $0 [--keep-worker] [--docker]"; exit 2 ;; esac
done
# Panes to stop: all of them, or all but the one titled "worker".
panes() {
  tmux list-panes -s -t "$SESSION" -F '#{pane_id} #{pane_title}' 2>/dev/null     | awk -v keep="$KEEP" '!(keep == 1 && $2 == "worker") {print $1}'
}

echo "== Stop the wheels"
if [ "$OFB_ROS_MODE" = native ] || [ "$OFB_ROS_MODE" = docker ]; then
  timeout 15 "$OFB_ROBOT_DIR/lib/ros_exec.sh" ros2 topic pub --once /cmd_vel geometry_msgs/msg/Twist "{}" >/dev/null 2>&1 \
    && echo "  [OK]   zero /cmd_vel sent" || echo "  [..]   could not publish /cmd_vel (bringup not running?)"
fi

if tmux has-session -t "$SESSION" 2>/dev/null; then
  echo "== Ctrl+C to every pane in '$SESSION'"
  for p in $(panes); do tmux send-keys -t "$p" C-c; done
  sleep 5
  for p in $(panes); do tmux send-keys -t "$p" C-c; done
  sleep 3
  if [ "$KEEP" = 1 ] && tmux list-panes -s -t "$SESSION" -F '#{pane_title}' | grep -qx worker; then
    for p in $(panes); do tmux kill-pane -t "$p" 2>/dev/null; done
    echo "  [OK]   panes closed; the vision worker keeps running in '$SESSION'"
  else
    tmux kill-session -t "$SESSION" 2>/dev/null && echo "  [OK]   tmux session '$SESSION' closed"
  fi
else
  echo "  [..]   no tmux session '$SESSION'"
fi

# Leftovers (a pane closed by hand, a crashed launch).
PATTERN='turtlebot3_ros|amcl|bt_navigator|controller_server|planner_server|map_server|vision_worker.py|objmem_ros'
if [ "$KEEP" = 1 ]; then PATTERN='turtlebot3_ros|amcl|bt_navigator|controller_server|planner_server|map_server|objmem_ros'; fi
LEFT="$(pgrep -fa "$PATTERN" 2>/dev/null | grep -v pgrep || true)"
if [ -n "$LEFT" ]; then
  echo "  [..]   still running:"; echo "$LEFT" | sed 's/^/         /'
  echo "         stop them with: pkill -INT -f '<name>'  (in Docker mode: ./robot/docker/run.sh stop)"
else
  echo "  [OK]   no robot processes left"
fi
if [ "$DOCKER" = 1 ]; then "$OFB_ROBOT_DIR/docker/run.sh" stop; fi
