#!/usr/bin/env bash
# Send one Nav2 goal from the terminal and wait for the result (nav.sh running,
# initial pose set). Ctrl+C cancels the goal.
#
# Usage: ./robot/goto.sh x y yaw [timeout_s]    map frame, meters and radians
#        ./robot/goto.sh --ahead 0.5            0.5 m straight ahead of the current pose
set -uo pipefail
source "$(dirname "$0")/env.sh"
ofb_need_ros "$0" "$@"
ofb_log_init goto

if [ "${1:-}" = "--ahead" ]; then
  D="${2:-0.5}"; TIMEOUT_S="${3:-90}"
  if ! CUR="$(ofb_python "$OFB_ROBOT_DIR/lib/ros_pose.py" --timeout 10)"; then
    fail "no map -> base_link transform" "nav.sh running? ./robot/set_initial_pose.sh done?"; ofb_summary; exit 1
  fi
  read -r X Y YAW < <(ofb_python -c "import math,sys; x,y,t=map(float,sys.argv[1:4]); d=float(sys.argv[4]); print('%.3f %.3f %.3f' % (x+d*math.cos(t), y+d*math.sin(t), t))" $CUR "$D")
  info "current pose $CUR -> goal $X $Y $YAW"
else
  if [ $# -lt 3 ]; then echo "usage: $0 x y yaw [timeout_s] | $0 --ahead <meters>"; exit 2; fi
  X="$1"; Y="$2"; YAW="$3"; TIMEOUT_S="${4:-90}"
fi
read -r QZ QW < <(ofb_python -c "import math,sys; y=float(sys.argv[1]); print('%.6f %.6f' % (math.sin(y/2), math.cos(y/2)))" "$YAW") \
  || { echo "[FAIL] x y yaw must be numbers"; exit 2; }

if ros2 action list 2>/dev/null | grep -x /navigate_to_pose >/dev/null; then ok "Nav2 action /navigate_to_pose"; else
  fail "no /navigate_to_pose action" "start ./robot/nav.sh <map> and wait until it prints 'Managed nodes are active'"
  ofb_summary; exit 1
fi

GOAL="{pose: {header: {frame_id: map}, pose: {position: {x: $X, y: $Y, z: 0.0}, orientation: {x: 0.0, y: 0.0, z: $QZ, w: $QW}}}}"
OUT="$OFB_LOG_DIR/goto_result.txt"
T0=$(date +%s)
info "goal x=$X y=$Y yaw=$YAW (timeout ${TIMEOUT_S}s)"
timeout --foreground -s INT "$TIMEOUT_S" ros2 action send_goal /navigate_to_pose nav2_msgs/action/NavigateToPose "$GOAL" \
  | tee "$OUT" | grep -E 'Goal (accepted|rejected)|status|Result' || true
DT=$(( $(date +%s) - T0 ))
if grep -q 'SUCCEEDED' "$OUT"; then
  ok "goal reached in ${DT}s"
else
  fail "goal not reached after ${DT}s ($(grep -o 'status: [A-Z]*' "$OUT" | tail -n 1))" \
       "path blocked? goal inside an obstacle? initial pose wrong? check ./robot/check_stage3.sh"
  timeout 5 ros2 topic pub --once /cmd_vel geometry_msgs/msg/Twist "{}" >/dev/null 2>&1 || true
fi
if POSE="$(ofb_python "$OFB_ROBOT_DIR/lib/ros_pose.py" --timeout 5)"; then
  ERR="$(ofb_python -c "import math,sys; a=list(map(float,sys.argv[1:4])); b=list(map(float,sys.argv[4:7])); print('%.2f m, %.0f deg' % (math.hypot(a[0]-b[0],a[1]-b[1]), abs(math.degrees(math.atan2(math.sin(a[2]-b[2]),math.cos(a[2]-b[2]))))))" $POSE "$X" "$Y" "$YAW")"
  info "final pose $POSE, error to goal $ERR"
fi
ofb_summary
