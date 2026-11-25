#!/usr/bin/env bash
# Start the robot: OpenCR (motors, wheel odometry, IMU) and the LiDAR.
# Leave it running (tmux pane). Stop with Ctrl+C.
#
# Usage: ./robot/bringup.sh
#   LDS_MODEL=LDS-01 ./robot/bringup.sh   if the LiDAR sticker says LDS-01
set -uo pipefail
source "$(dirname "$0")/env.sh"
ofb_need_ros "$0" "$@"
ofb_log_init bringup

echo "== Devices"
if [ -e "$OPENCR_PORT" ]; then ok "OpenCR at $OPENCR_PORT"; else
  fail "no $OPENCR_PORT" "OpenCR USB cable to the Jetson, robot power switch ON; ls /dev/ttyACM*; set OPENCR_PORT"
fi
if [ -e "$LIDAR_PORT" ]; then ok "LiDAR at $LIDAR_PORT"; else
  fail "no $LIDAR_PORT" "LiDAR USB adapter to the Jetson; ls /dev/ttyUSB*; set LIDAR_PORT"
fi
for d in "$OPENCR_PORT" "$LIDAR_PORT"; do
  if [ -e "$d" ] && [ ! -w "$d" ]; then
    fail "$d not writable by $(id -un)" "sudo cp robot/udev/99-ofb-robot.rules /etc/udev/rules.d/ && sudo udevadm trigger"
  fi
done
case "$LDS_MODEL" in
  LDS-01|LDS-02) ok "LDS_MODEL=$LDS_MODEL" ;;
  *) fail "LDS_MODEL=$LDS_MODEL" "use LDS-01 or LDS-02 (sticker on the LiDAR)" ;;
esac
if [ "$LDS_MODEL" = LDS-02 ] && ! ros2 pkg prefix ld08_driver >/dev/null 2>&1; then
  fail "ld08_driver (LDS-02 driver) not installed" "rerun ./robot/install_foxy_jetson.sh, or try LDS_MODEL=LDS-01"
fi
if pgrep -f turtlebot3_ros >/dev/null 2>&1; then
  fail "turtlebot3_ros already running" "only one bringup at a time: ./robot/stop_all.sh, or Ctrl+C the other pane"
fi
if [ "$OFB_N_FAIL" -gt 0 ]; then ofb_summary; exit 1; fi

# Files that earlier ROS processes left in /dev/shm (Fast DDS shared memory) make new
# nodes deaf: bringup ran with /odom published but nobody could hear it (2026-11-25,
# 30-61 stale files). Remove them, but only when none of our ROS processes is running
# (the vision worker is not a ROS process: it does not matter here).
if ! pgrep -u "$(id -u)" -f 'turtlebot3_ros|ld08_driver|nav2_|slam_toolbox|objmem_ros|_ros2_daemon' >/dev/null 2>&1; then
  rm -f /dev/shm/fastrtps_* /dev/shm/sem.fastrtps_* 2>/dev/null || true
fi

LAUNCH=(turtlebot3_bringup robot.launch.py)
TB3_LAUNCH_FILE="$(ros2 pkg prefix turtlebot3_bringup 2>/dev/null)/share/turtlebot3_bringup/launch/robot.launch.py"
if [ "$LDS_MODEL" = LDS-02 ] && [ -f "$TB3_LAUNCH_FILE" ] && ! grep LDS_MODEL "$TB3_LAUNCH_FILE" >/dev/null; then
  # Foxy's robot.launch.py always starts the LDS-01 driver (no /scan with an LDS-02).
  info "this turtlebot3_bringup ignores LDS_MODEL; using robot/launch/robot_ld08.launch.py (ld08_driver)"
  LAUNCH=("$OFB_ROBOT_DIR/launch/robot_ld08.launch.py")
fi

echo "== Starting turtlebot3_bringup (Ctrl+C to stop). Check it from another pane: ./robot/check_stage1.sh"
ros2 launch "${LAUNCH[@]}" usb_port:="$OPENCR_PORT"
status=$?
echo "== bringup exited with status $status"
if [ "$status" -ne 0 ] && [ "$status" -ne 130 ]; then
  echo "[FAIL] bringup stopped"
  echo "       hint: 'Failed to open the port' -> cable / OPENCR_PORT; 'Failed connection with Devices'"
  echo "             -> OpenCR firmware does not match ROS 2 (robot/README.md, 'OpenCR firmware')"
fi
exit "$status"
