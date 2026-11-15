#!/usr/bin/env bash
# Build a map with slam_toolbox while you drive with teleop.sh.
# bringup.sh must be running. When the map looks complete, run
# ./robot/save_map.sh <name> in another pane, then Ctrl+C here.
#
# Usage: ./robot/slam.sh [slam_toolbox|cartographer]
#
# No RViz in the classroom: watch progress with ./robot/check_stage2.sh, which
# prints the map size, or save often with save_map.sh and look at the .pgm.
set -uo pipefail
source "$(dirname "$0")/env.sh"
ofb_need_ros "$0" "$@"
ofb_log_init slam

METHOD="${1:-slam_toolbox}"
echo "== Checks"
if ofb_wait_topic /scan 10; then ok "/scan"; else fail "no /scan" "start ./robot/bringup.sh first"; fi
if ofb_wait_topic /odom 5; then ok "/odom"; else fail "no /odom" "start ./robot/bringup.sh first"; fi
if pgrep -f 'amcl|async_slam_toolbox|sync_slam_toolbox|cartographer_node' >/dev/null 2>&1; then
  fail "SLAM or AMCL already running" "stop nav.sh / the other slam.sh first (only one map->odom source)"
fi
if [ "$OFB_N_FAIL" -gt 0 ]; then ofb_summary; exit 1; fi

echo "== Starting $METHOD. Drive slowly, keep turns short, and come back to the start once (loop closure)."
case "$METHOD" in
  slam_toolbox)
    # use_sim_time defaults to true in the Foxy launch file: force it off.
    ros2 launch slam_toolbox online_async_launch.py use_sim_time:=false ;;
  cartographer)
    ros2 launch turtlebot3_cartographer cartographer.launch.py use_sim_time:=False use_rviz:=False ;;
  *)
    echo "[FAIL] unknown method $METHOD (slam_toolbox | cartographer)"; exit 2 ;;
esac
