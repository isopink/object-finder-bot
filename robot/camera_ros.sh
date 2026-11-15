#!/usr/bin/env bash
# Start a ROS camera node, only for image_source:=ros (OFB_IMAGE_SOURCE=ros).
# With the default image_source:=worker the vision worker opens the camera
# itself and this script is not needed.
#
# Usage: ./robot/camera_ros.sh depth|nodepth
#   depth    realsense2_camera: color (compressed), depth aligned to color, camera_info
#   nodepth  v4l2_camera on /dev/video0 (C920): /image_raw, /image_raw/compressed, /camera_info
set -uo pipefail
source "$(dirname "$0")/env.sh"
ofb_need_ros "$0" "$@"
ofb_log_init camera_ros

MODE="${1:-}"
case "$MODE" in
  depth)
    if ros2 pkg prefix realsense2_camera >/dev/null 2>&1; then ok "realsense2_camera installed"; else
      fail "realsense2_camera missing" "Foxy: ./robot/install_foxy_jetson.sh --with-cameras"; ofb_summary; exit 1
    fi
    # align_depth (older wrapper) and align_depth.enable (4.x) are both passed; the unused one is ignored.
    ros2 launch realsense2_camera rs_launch.py \
      align_depth:=true align_depth.enable:=true \
      enable_color:=true enable_depth:=true \
      rgb_camera.profile:=640x480x15 depth_module.profile:=640x480x15 \
      color_width:=640 color_height:=480 depth_width:=640 depth_height:=480 color_fps:=15.0 depth_fps:=15.0
    ;;
  nodepth)
    DEV="${OFB_VIDEO_DEVICE:-/dev/video0}"
    if [ -e "$DEV" ]; then ok "camera $DEV"; else
      fail "no $DEV" "plug in the C920; v4l2-ctl --list-devices; set OFB_VIDEO_DEVICE"; ofb_summary; exit 1
    fi
    ros2 run v4l2_camera v4l2_camera_node --ros-args \
      -p video_device:="$DEV" -p image_size:="[640,480]" -p pixel_format:=YUYV
    ;;
  *) echo "usage: $0 depth|nodepth"; exit 2 ;;
esac
