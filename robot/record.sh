#!/usr/bin/env bash
# Record a rosbag of the robot sensors to robot/bags/<timestamp>/ (bringup.sh running).
# Record WITHOUT slam.sh/nav.sh running if the bag is for replay.sh: otherwise
# map->odom ends up in /tf and fights the SLAM you replay. Ctrl+C to stop.
#
# Usage: ./robot/record.sh [--camera] [extra topics...]
#   --camera  also record the camera topics (only exist with image_source:=ros,
#             i.e. a realsense2_camera or v4l2_camera node is running)
# Storage: sqlite3 (works on Foxy and Humble). OFB_BAG_STORAGE=mcap to change.
set -uo pipefail
source "$(dirname "$0")/env.sh"
ofb_need_ros "$0" "$@"
ofb_log_init record

TOPICS=(/scan /odom /tf /tf_static /imu /joint_states /cmd_vel)
if [ "${1:-}" = "--camera" ]; then
  shift
  TOPICS+=(
    "${OFB_COLOR_TOPIC:-/camera/color/image_raw/compressed}"
    "${OFB_DEPTH_TOPIC:-/camera/aligned_depth_to_color/image_raw}"
    "${OFB_INFO_TOPIC:-/camera/color/camera_info}"
    /image_raw/compressed /camera_info
  )
fi
TOPICS+=("$@")

echo "== Checks"
for t in /scan /odom; do
  if ofb_wait_topic "$t" 10; then ok "$t"; else fail "no $t" "start ./robot/bringup.sh first"; fi
done
if pgrep -f 'async_slam_toolbox|amcl' >/dev/null 2>&1; then
  info "SLAM or AMCL is running: this bag will contain map->odom (fine for viewing, not for replay.sh)"
fi
AVAILABLE="$(ros2 topic list 2>/dev/null)"
REC=()
for t in "${TOPICS[@]}"; do
  if grep -qx "$t" <<<"$AVAILABLE"; then REC+=("$t"); else info "skip $t (not published)"; fi
done
if [ "$OFB_N_FAIL" -gt 0 ] || [ "${#REC[@]}" -eq 0 ]; then ofb_summary; exit 1; fi

mkdir -p "$OFB_ROBOT_DIR/bags"
BAG="$OFB_ROBOT_DIR/bags/$(date +%Y%m%d_%H%M%S)"
echo "== Recording ${REC[*]}"
echo "   to $BAG  (Ctrl+C to stop; drive with ./robot/teleop.sh in another pane)"
ros2 bag record -s "${OFB_BAG_STORAGE:-sqlite3}" -o "$BAG" "${REC[@]}"
echo "== Saved $BAG"
ros2 bag info "$BAG" 2>/dev/null | head -n 20
echo "Copy to the laptop: scp -r <user>@<jetson-ip>:$BAG ./"
