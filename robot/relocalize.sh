#!/usr/bin/env bash
# Tell AMCL where the robot really is, without knowing it: match the LiDAR scan against the
# full SLAM map (robot/lib/relocalize.py) and set that pose as AMCL's initial pose.
# Use it after the robot was carried, after a restart away from the map origin, or when the
# map view shows the robot in the wrong place. The robot must stand still (about 30 s).
#
# Usage: ./robot/relocalize.sh [map]        default: the newest robot/maps/*_nav.yaml's full map
#        ./robot/relocalize.sh room_l4 --check   only compare AMCL's pose with the scan match
set -uo pipefail
source "$(dirname "$0")/env.sh"
ofb_need_ros "$0" "$@"
ofb_log_init relocalize

MAP="${1:-}"; CHECK=0
for a in "$@"; do [ "$a" = "--check" ] && CHECK=1; done
if [ -z "$MAP" ] || [ "$MAP" = "--check" ]; then
  MAP="$(ls -t "$OFB_ROBOT_DIR"/maps/*_nav.yaml 2>/dev/null | head -1)"
fi
case "$MAP" in *.yaml) ;; *) MAP="$OFB_ROBOT_DIR/maps/$MAP.yaml" ;; esac
FULL="${MAP%_nav.yaml}.yaml"                    # <name>_nav.yaml -> <name>.yaml
if [ ! -f "$FULL" ]; then fail "no map $FULL" "give the SLAM map name, e.g. ./robot/relocalize.sh room_l4"; ofb_summary; exit 1; fi
info "matching the scan against $(basename "$FULL") (stand still)"

CUR="$(ofb_python "$OFB_ROBOT_DIR/lib/ros_pose.py" --timeout 5 2>/dev/null | tail -1 || true)"
OUT="$(/usr/bin/python3 "$OFB_ROBOT_DIR/lib/relocalize.py" "$FULL" ${CUR:+--compare "$CUR"} 2>&1)"
echo "$OUT" | grep -v "^POSE" | sed 's/^/         /'
POSE="$(echo "$OUT" | sed -n 's/^POSE //p' | tail -1)"
if [ -z "$POSE" ] || [ "$POSE" = none ]; then
  fail "the scan does not fit the map anywhere" "is this the right map? is the LiDAR running?"; ofb_summary; exit 1
fi
read -r X Y YAW SCORE <<< "$POSE"
ok "scan match: x $X y $Y yaw $YAW (score $SCORE)"
if [ "$CHECK" = 1 ]; then ofb_summary; exit 0; fi
if "$OFB_ROBOT_DIR/set_initial_pose.sh" "$X" "$Y" "$YAW"; then ok "AMCL initial pose set"; else
  fail "could not set the initial pose" "is nav.sh (AMCL) running?"
fi
ofb_summary
