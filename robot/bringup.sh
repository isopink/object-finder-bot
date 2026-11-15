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

echo "== Starting turtlebot3_bringup (Ctrl+C to stop). Check it from another pane: ./robot/check_stage1.sh"
ros2 launch turtlebot3_bringup robot.launch.py usb_port:="$OPENCR_PORT"
status=$?
echo "== bringup exited with status $status"
if [ "$status" -ne 0 ] && [ "$status" -ne 130 ]; then
  echo "[FAIL] bringup stopped"
  echo "       hint: 'Failed to open the port' -> cable / OPENCR_PORT; 'Failed connection with Devices'"
  echo "             -> OpenCR firmware does not match ROS 2 (robot/README.md, 'OpenCR firmware')"
fi
exit "$status"
