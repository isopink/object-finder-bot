#!/usr/bin/env bash
# Patrol: drive through saved waypoints and stop at each one so the observer
# can record the desks (it records only while the robot stands still).
# Replaces "drive around with teleop" in stage 5 and in the demo.
#
# The Nav2 waypoint follower's wait-at-waypoint plugin and nav2_simple_commander
# are not in Foxy, so this loops over goto.sh (NavigateToPose) and sleeps.
#
# Usage (nav.sh running, initial pose set):
#   ./robot/patrol.sh --add [room429]     save the current pose as the next waypoint
#                                          (drive there with teleop, face the desk, run this)
#   ./robot/patrol.sh --list [room429]    show the waypoints
#   ./robot/patrol.sh [room429] [rounds] [stop_s]   patrol (default 1 round, 3 s per stop)
#   ./robot/patrol.sh --clear [room429]   delete the waypoint file
# Waypoints: robot/config/patrol_<map>.txt, one "x y yaw" per line (map frame).
set -uo pipefail
source "$(dirname "$0")/env.sh"
ofb_need_ros "$0" "$@"

ACTION=run
case "${1:-}" in --add|--list|--clear) ACTION="${1#--}"; shift ;; esac
MAP="${1:-room429}"
FILE="$OFB_ROBOT_DIR/config/patrol_${MAP}.txt"

case "$ACTION" in
  add)
    if ! POSE="$(ofb_python "$OFB_ROBOT_DIR/lib/ros_pose.py" --timeout 10)"; then
      echo "[FAIL] no map -> base_link transform: nav.sh running? set_initial_pose.sh done?"; exit 1
    fi
    mkdir -p "$(dirname "$FILE")"
    echo "$POSE" >> "$FILE"
    echo "[OK]   waypoint $(grep -c . "$FILE"): $POSE  -> $FILE"
    exit 0 ;;
  list)
    if [ -s "$FILE" ]; then nl -w2 -s'  ' "$FILE"; else echo "no waypoints in $FILE (use --add)"; fi
    exit 0 ;;
  clear)
    rm -f "$FILE" && echo "[OK]   removed $FILE"; exit 0 ;;
esac

ofb_log_init patrol
ROUNDS="${2:-1}"; STOP_S="${3:-3}"
if [ ! -s "$FILE" ]; then
  fail "no waypoints in $FILE" "drive to each desk with teleop and run ./robot/patrol.sh --add $MAP"
  ofb_summary; exit 1
fi
mapfile -t WPS < <(grep -v '^\s*#' "$FILE" | grep -v '^\s*$')
info "${#WPS[@]} waypoints x $ROUNDS round(s), ${STOP_S}s stop each (Ctrl+C stops the patrol)"
trap 'echo; info "patrol stopped"; timeout 5 ros2 topic pub --once /cmd_vel geometry_msgs/msg/Twist "{}" >/dev/null 2>&1; ofb_summary; exit 130' INT TERM

for ((r = 1; r <= ROUNDS; r++)); do
  for i in "${!WPS[@]}"; do
    read -r X Y YAW _ <<<"${WPS[$i]}"
    echo "== round $r, waypoint $((i + 1))/${#WPS[@]}: $X $Y $YAW"
    if "$OFB_ROBOT_DIR/goto.sh" "$X" "$Y" "$YAW" 90 | grep -E '\[(OK|FAIL)\]'; then :; fi
    # The observer records only while the robot is stopped: give it time.
    sleep "$STOP_S"
  done
done
ok "patrol finished"
ofb_summary
