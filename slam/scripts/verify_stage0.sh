#!/usr/bin/env bash
# Verify SLAM on the real Waffle Pi and record a rosbag (run on the Jetson or a lab PC).
# robot_bringup.sh must already be running on the Waffle Pi.
# Usage: ./verify_stage0.sh [cartographer|slam_toolbox|record]
#   record: record sensor data only, without SLAM (use this mode for bags fed to replay_bag.sh).
#           Recording while SLAM runs puts map->odom into /tf, which conflicts on replay.
set -eo pipefail
source "$(dirname "$0")/env.sh"

METHOD="${1:-slam_toolbox}"
STAMP="$(date +%Y%m%d_%H%M%S)"
LOG_DIR="$SLAM_DIR/logs/$STAMP"
mkdir -p "$LOG_DIR" "$SLAM_DIR/bags"
exec > >(tee "$LOG_DIR/verify.log") 2>&1

echo "== Env: ROS_DISTRO=$ROS_DISTRO ROS_DOMAIN_ID=$ROS_DOMAIN_ID MODEL=$TURTLEBOT3_MODEL"

echo "== 1. Check robot topics (10 s timeout)"
for t in /scan /odom /tf; do
  if timeout 10 ros2 topic echo --once "$t" > /dev/null 2>&1; then
    echo "  [OK]   $t"
  else
    echo "  [FAIL] $t  -> check robot bringup, Wi-Fi, ROS_DOMAIN_ID, multicast"
    FAILED=1
  fi
done
[ -z "${FAILED:-}" ] || exit 1

echo "== 2. Topic rate"
timeout 5 ros2 topic hz /scan || true

echo "== 3. Start rosbag recording"
ros2 bag record -s mcap -o "$SLAM_DIR/bags/stage0_$STAMP" /scan /odom /tf /tf_static /imu &
BAG_PID=$!
trap 'kill -INT $BAG_PID 2>/dev/null; wait $BAG_PID 2>/dev/null' EXIT

echo "== 4. Running $METHOD. Drive with teleop in another terminal (in SLAM mode, run save_map.sh lab_$STAMP before quitting)"
case "$METHOD" in
  cartographer) ros2 launch turtlebot3_cartographer cartographer.launch.py ;;
  slam_toolbox) ros2 launch slam_toolbox online_async_launch.py ;;
  record)       echo "Recording. Drive with teleop, then press Ctrl+C"; wait $BAG_PID ;;
  *)            echo "Unknown method: $METHOD" >&2; exit 1 ;;
esac
