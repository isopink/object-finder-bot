#!/usr/bin/env bash
# Stage 1: robot bringup and teleop.
# Checks the USB devices, the ROS setup, and (with bringup.sh running in another
# pane) /scan, /odom, /tf, the battery, and a short in-place turn.
#
# Usage: ./robot/check_stage1.sh [--no-drive]
#   --no-drive  skip the 3 s in-place turn (the robot turns ~50 degrees otherwise)
set -uo pipefail
source "$(dirname "$0")/env.sh"
ofb_need_ros "$0" "$@"
ofb_log_init check_stage1

DRIVE=1
[ "${1:-}" = "--no-drive" ] && DRIVE=0

echo "== 1. USB devices (lsusb)"
USB="$(lsusb 2>/dev/null || true)"
grep -qi '0483:5740' <<<"$USB" && ok "OpenCR (0483:5740)" || fail "OpenCR not on USB" "micro-USB cable OpenCR -> Jetson; robot power switch ON (OpenCR LEDs lit)"
grep -qi '10c4:ea60' <<<"$USB" && ok "LiDAR USB adapter (10c4:ea60)" || fail "LiDAR adapter not on USB" "LiDAR board USB -> Jetson; LDS-02 uses the same CP2102 adapter"
grep -qi '8086:' <<<"$USB" && ok "Intel RealSense" || info "no RealSense (needed for depth mode only)"
grep -qi '046d:08' <<<"$USB" && ok "Logitech camera (C920)" || info "no C920 (needed for nodepth mode only)"

echo "== 2. Serial ports"
for d in "$OPENCR_PORT" "$LIDAR_PORT"; do
  if [ -e "$d" ]; then
    if [ -r "$d" ] && [ -w "$d" ]; then ok "$d readable and writable"; else
      fail "$d exists but no permission" "sudo cp robot/udev/99-ofb-robot.rules /etc/udev/rules.d/ && sudo udevadm trigger; or sudo usermod -aG dialout $USER and log in again"
    fi
  else
    fail "$d missing" "ls /dev/ttyACM* /dev/ttyUSB*; set OPENCR_PORT / LIDAR_PORT in the environment"
  fi
done

echo "== 3. ROS setup"
ok "ROS_DISTRO=$ROS_DISTRO ($(command -v ros2))"
for p in turtlebot3_bringup turtlebot3_teleop slam_toolbox nav2_bringup; do
  check "package $p" "./robot/install_foxy_jetson.sh (Foxy) or ./robot/docker/run.sh build (Humble)" ros2 pkg prefix "$p"
done
if [ "$LDS_MODEL" = LDS-02 ]; then
  check "package ld08_driver (LDS-02)" "./robot/install_foxy_jetson.sh builds it; or LDS_MODEL=LDS-01" ros2 pkg prefix ld08_driver
fi

echo "== 4. Robot topics (bringup.sh must be running)"
if ! ofb_wait_topic /odom 10; then
  fail "no /odom" "start ./robot/bringup.sh in another tmux pane, wait for 'Run!', rerun this check"
  ofb_summary; exit 1
fi
for t in /scan /odom /tf /imu /joint_states; do
  if ofb_wait_topic "$t" 10; then ok "$t"; else fail "no $t" "read the bringup pane for errors (robot/logs/*/bringup.log)"; fi
done
HZ="$(ofb_topic_hz /scan 10)"
if [ -n "$HZ" ]; then
  awk -v r="$HZ" 'BEGIN { exit !(r > 3) }' && ok "/scan at $HZ Hz" || fail "/scan only $HZ Hz" "LiDAR expected ~5 Hz; check LDS_MODEL and the LiDAR cable"
else
  fail "/scan rate unknown" "ros2 topic hz /scan"
fi
HZ="$(ofb_topic_hz /odom 10)"
[ -n "$HZ" ] && ok "/odom at $HZ Hz" || fail "/odom rate unknown" "ros2 topic hz /odom"
VALID="$(timeout 10 ros2 topic echo /scan 2>/dev/null | awk '/^ranges:/ {on=1; next} on && /^- / {n++; if ($2+0 > 0.05 && $2 != ".inf") v++} on && /^[a-z]/ {print v+0 "/" n+0; exit}')"
if [ -n "$VALID" ]; then
  [ "${VALID%%/*}" -gt 50 ] && ok "one scan: $VALID beams with a range" || fail "one scan: only $VALID beams with a range" "LiDAR spinning? remove anything covering it"
fi
VOLT="$(timeout 10 ros2 topic echo /battery_state 2>/dev/null | awk '/^voltage:/ {print $2; exit}')"
if [ -n "$VOLT" ]; then
  awk -v v="$VOLT" 'BEGIN { exit !(v >= 11.0) }' && ok "battery ${VOLT} V" || fail "battery ${VOLT} V (low)" "charge the battery (11.1 V pack; below 11 V the OpenCR beeps)"
else
  info "no /battery_state reading"
fi

echo "== 5. TF odom -> base_link"
if P0="$(ofb_python "$OFB_ROBOT_DIR/lib/ros_pose.py" --parent odom --timeout 10)"; then
  ok "odom -> base_link: $P0 (x y yaw)"
else
  fail "no odom -> base_link" "bringup publishes it; read the bringup pane"
  ofb_summary; exit 1
fi

echo "== 6. Short turn in place (teleop check)"
if [ "$DRIVE" = 1 ]; then
  echo "  the robot will turn left in place for 3 s; Ctrl+C now to skip"
  sleep 3
  timeout 3 ros2 topic pub -r 10 /cmd_vel geometry_msgs/msg/Twist "{angular: {z: 0.3}}" >/dev/null 2>&1
  timeout 5 ros2 topic pub --once /cmd_vel geometry_msgs/msg/Twist "{}" >/dev/null 2>&1
  sleep 1
  if P1="$(ofb_python "$OFB_ROBOT_DIR/lib/ros_pose.py" --parent odom --timeout 5)"; then
    DYAW="$(ofb_python -c "import math,sys; a=float(sys.argv[1]); b=float(sys.argv[2]); print('%.0f' % math.degrees(math.atan2(math.sin(b-a), math.cos(b-a))))" "$(echo "$P0" | cut -d' ' -f3)" "$(echo "$P1" | cut -d' ' -f3)")"
    if [ "${DYAW#-}" -ge 15 ]; then ok "robot turned $DYAW deg (odometry follows /cmd_vel)"; else
      fail "robot turned only $DYAW deg" "wheels on the floor? motors powered (OpenCR switch)? emergency stop?"
    fi
  fi
  info "now drive by hand: ./robot/teleop.sh (w/x/a/d, s to stop)"
else
  info "skipped (--no-drive); try ./robot/teleop.sh"
fi

ofb_summary
echo "Copy back: scp -r <user>@<jetson-ip>:$OFB_LOG_DIR ./"
