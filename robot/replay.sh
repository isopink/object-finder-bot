#!/usr/bin/env bash
# Replay a bag made by record.sh, optionally re-running SLAM on it (simulated
# time). Do not run bringup.sh at the same time: the bag publishes /scan and /odom.
#
# Usage: ./robot/replay.sh <bag> [slam_toolbox|cartographer|none] [rate]
#   ./robot/replay.sh robot/bags/20261120_141500 slam_toolbox
#   then, before it ends: ./robot/save_map.sh replay_test
set -uo pipefail
source "$(dirname "$0")/env.sh"
ofb_need_ros "$0" "$@"
ofb_log_init replay

BAG="${1:-}"
METHOD="${2:-slam_toolbox}"
RATE="${3:-1.0}"
if [ -z "$BAG" ] || [ ! -d "$BAG" ]; then
  echo "usage: $0 <bag dir> [slam_toolbox|cartographer|none] [rate]"
  echo "bags: $(ls -d "$OFB_ROBOT_DIR"/bags/*/ 2>/dev/null | tr '\n' ' ')"
  exit 2
fi
if pgrep -f turtlebot3_ros >/dev/null 2>&1; then
  fail "bringup is running" "stop it first: the bag already contains /scan, /odom, /tf"; ofb_summary; exit 1
fi
ros2 bag info "$BAG" | head -n 20

# Foxy's `ros2 bag play` cannot publish /clock: SLAM then runs on wall time and
# uses the bag's message stamps through TF. Later distros replay with /clock.
SIM=true; CLOCK=(--clock)
if [ "$ROS_DISTRO" = foxy ]; then SIM=false; CLOCK=(); fi
PID=""
case "$METHOD" in
  slam_toolbox) ros2 launch slam_toolbox online_async_launch.py use_sim_time:=$SIM & PID=$! ;;
  cartographer) ros2 launch turtlebot3_cartographer cartographer.launch.py use_sim_time:=$SIM use_rviz:=False & PID=$! ;;
  none) ;;
  *) echo "[FAIL] unknown method $METHOD"; exit 2 ;;
esac
cleanup() { if [ -n "$PID" ]; then kill -INT "$PID" 2>/dev/null; wait "$PID" 2>/dev/null; fi; }
trap cleanup EXIT
if [ -n "$PID" ]; then sleep 5; fi

echo "== Playing $BAG at rate $RATE"
if ros2 bag play "$BAG" "${CLOCK[@]}" --rate "$RATE"; then ok "playback finished"; else fail "ros2 bag play failed" "is it a bag folder (metadata.yaml inside)?"; fi
if [ -n "$PID" ]; then
  echo "== Playback done. Save the map now from another pane (./robot/save_map.sh <name>), then press Enter here."
  read -r _ || true
fi
ofb_summary
