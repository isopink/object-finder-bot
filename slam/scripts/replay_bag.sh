#!/usr/bin/env bash
# Re-run SLAM on a recorded rosbag (tune parameters without the robot).
# Use a bag recorded with: verify_stage0.sh record
# Usage: ./replay_bag.sh <bag dir> [cartographer|slam_toolbox]
set -eo pipefail
source "$(dirname "$0")/env.sh"

BAG="${1:?bag directory required (e.g. ../bags/stage0_20261015_140000)}"
METHOD="${2:-slam_toolbox}"

case "$METHOD" in
  cartographer) ros2 launch turtlebot3_cartographer cartographer.launch.py use_sim_time:=True & ;;
  slam_toolbox) ros2 launch slam_toolbox online_async_launch.py use_sim_time:=True & ;;
  *)            echo "Unknown method: $METHOD" >&2; exit 1 ;;
esac
SLAM_PID=$!
trap 'kill $SLAM_PID 2>/dev/null' EXIT
sleep 5
ros2 bag play "$BAG" --clock
echo "Playback finished. Save the map with save_map.sh before quitting (Ctrl+C)."
wait $SLAM_PID
