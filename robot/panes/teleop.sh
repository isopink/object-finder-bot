#!/usr/bin/env bash
# Window "teleop" of the laptop launcher: the four-key teleop, restarted on Enter.
cd "$(dirname "$0")/../.." || exit 1
export OFB_DDS_WIDE="${OFB_DDS_WIDE:-1}" OFB_ODOM_IMU="${OFB_ODOM_IMU:-0}"
while true; do
  bash robot/teleop4.sh
  echo
  read -r -p "teleop closed. Enter = start it again, Ctrl+C = close this pane " _ || exit 0
done
