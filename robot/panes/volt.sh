#!/usr/bin/env bash
# Window "battery" of the laptop launcher: live battery voltage (bringup must be running).
cd "$(dirname "$0")/../.." || exit 1
export OFB_DDS_WIDE="${OFB_DDS_WIDE:-1}" OFB_ODOM_IMU="${OFB_ODOM_IMU:-0}"
source robot/env.sh >/dev/null 2>&1
set +u
echo "== battery voltage. 11.0-12.6 V is normal; below 11 V charge or swap the battery."
while true; do
  ros2 topic echo /battery_state 2>/dev/null | grep --line-buffered "^voltage" | while read -r _ v; do
    printf "%s  %.2f V\n" "$(date +%H:%M:%S)" "$v"
  done
  echo "$(date +%H:%M:%S)  no /battery_state (bringup not running?); trying again in 5 s"
  sleep 5
done
