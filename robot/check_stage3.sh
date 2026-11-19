#!/usr/bin/env bash
# Stage 3: localization on the saved map and one Nav2 goal.
# Needs bringup.sh and nav.sh <map> running, and the initial pose set.
#
# Usage: ./robot/check_stage3.sh                 drive 0.5 m ahead, then back
#        ./robot/check_stage3.sh x y yaw         drive to a map pose, then back
set -uo pipefail
source "$(dirname "$0")/env.sh"
ofb_need_ros "$0" "$@"
ofb_log_init check_stage3

echo "== 1. Nav2 nodes"
NODES="$(ros2 node list 2>/dev/null)"
for n in map_server amcl controller_server planner_server bt_navigator; do
  if grep -q "/$n\$" <<<"$NODES"; then ok "node $n"; else fail "node $n missing" "start ./robot/nav.sh <map>; read its pane for errors"; fi
done
for n in map_server amcl bt_navigator; do
  S="$(timeout 10 ros2 lifecycle get "/$n" 2>/dev/null | head -n 1)"
  case "$S" in
    active*) ok "$n is active" ;;
    *) fail "$n state: ${S:-unknown}" "nav.sh prints 'Managed nodes are active' when ready; a wrong map path stops map_server" ;;
  esac
done
if [ -n "$(timeout 10 ros2 topic echo --qos-durability transient_local --qos-reliability reliable /map 2>/dev/null | head -n 1)" ]; then
  ok "/map served"
else
  fail "/map not received" "map_server not active, or wrong map file"
fi

echo "== 2. Localization"
if P0="$(ofb_python "$OFB_ROBOT_DIR/lib/ros_pose.py" --parent map --timeout 10)"; then
  ok "map -> base_link: $P0 (x y yaw)"
else
  fail "no map -> base_link" "set the initial pose: ./robot/set_initial_pose.sh x y yaw"
  ofb_summary; exit 1
fi
COV="$(timeout 10 ros2 topic echo /amcl_pose 2>/dev/null | awk '/^  covariance:/ {on=1; next} on && /^ *- / {n++; if (n==1) xx=$2; if (n==8) yy=$2} on && n>=8 {print xx, yy; exit}')"
if [ -n "$COV" ]; then
  read -r CXX CYY <<<"$COV"
  awk -v a="$CXX" -v b="$CYY" 'BEGIN { exit !(a < 0.1 && b < 0.1) }' \
    && ok "AMCL covariance xx=$CXX yy=$CYY (converged)" \
    || fail "AMCL covariance xx=$CXX yy=$CYY (not converged)" "turn in place a little with teleop.sh, or set the initial pose again"
else
  info "no /amcl_pose message (AMCL publishes when the robot moves); continuing"
fi

echo "== 3. One Nav2 goal and back"
if [ $# -ge 3 ]; then
  "$OFB_ROBOT_DIR/goto.sh" "$1" "$2" "$3" 120 && ok "goal $1 $2 $3 reached" || fail "goal $1 $2 $3 not reached" "read $OFB_LOG_DIR/goto.log"
else
  "$OFB_ROBOT_DIR/goto.sh" --ahead 0.5 90 && ok "goal 0.5 m ahead reached" || fail "goal 0.5 m ahead not reached" "is there 1 m of free floor in front? read $OFB_LOG_DIR/goto.log"
fi
# shellcheck disable=SC2086
"$OFB_ROBOT_DIR/goto.sh" $P0 120 && ok "back at the start pose" || fail "return to start failed" "read $OFB_LOG_DIR/goto.log"

ofb_summary
echo "Copy back: scp -r <user>@<jetson-ip>:$OFB_LOG_DIR ./"
