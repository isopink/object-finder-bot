#!/usr/bin/env bash
# Tell AMCL where the robot is on the map (replaces "2D Pose Estimate" in RViz).
# nav.sh must be running.
#
# Usage: ./robot/set_initial_pose.sh x y yaw     meters, meters, radians (map frame)
#   If the robot stands where mapping started, facing the same way: 0 0 0
#
# Afterwards, turn the robot in place a little (teleop a/d) so AMCL converges.
set -uo pipefail
source "$(dirname "$0")/env.sh"
ofb_need_ros "$0" "$@"
ofb_log_init set_initial_pose

if [ $# -ne 3 ]; then echo "usage: $0 x y yaw   (e.g. $0 0 0 0)"; exit 2; fi
X="$1"; Y="$2"; YAW="$3"
read -r QZ QW < <(ofb_python -c "import math,sys; y=float(sys.argv[1]); print('%.6f %.6f' % (math.sin(y/2), math.cos(y/2)))" "$YAW") \
  || { echo "[FAIL] yaw must be a number in radians"; exit 2; }

if ofb_wait_topic /amcl_pose 1 || pgrep -f amcl >/dev/null 2>&1; then ok "AMCL is running"; else
  fail "AMCL not found" "start ./robot/nav.sh <map> first"; ofb_summary; exit 1
fi

# Covariance: 0.5 m std in x and y, ~15 deg in yaw.
MSG="{header: {frame_id: map}, pose: {pose: {position: {x: $X, y: $Y, z: 0.0}, orientation: {x: 0.0, y: 0.0, z: $QZ, w: $QW}}, covariance: [0.25, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.25, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0685]}}"
# Publish a few times: the first message can be lost while discovery runs.
for _ in 1 2 3; do
  timeout 10 ros2 topic pub --once /initialpose geometry_msgs/msg/PoseWithCovarianceStamped "$MSG" >/dev/null 2>&1
  sleep 1
done
info "published /initialpose x=$X y=$Y yaw=$YAW"

if POSE="$(ofb_python "$OFB_ROBOT_DIR/lib/ros_pose.py" --timeout 10)"; then
  ok "map -> base_link now: $POSE (x y yaw)"
else
  fail "no map -> base_link transform" "is bringup.sh running? AMCL needs /scan and odom -> base_link"
fi
ofb_summary
