#!/usr/bin/env bash
# Stage 2: SLAM and a saved map.
# While slam.sh runs: checks /map and map -> odom, saves the map as <name>, and
# prints its size. Without SLAM running: checks the saved robot/maps/<name>.
#
# Usage: ./robot/check_stage2.sh <name>
set -uo pipefail
source "$(dirname "$0")/env.sh"
ofb_need_ros "$0" "$@"
ofb_log_init check_stage2

NAME="${1:-}"
if [ -z "$NAME" ]; then echo "usage: $0 <map name>"; exit 2; fi
OUT="$OFB_ROBOT_DIR/maps/$NAME"

if pgrep -f 'async_slam_toolbox|sync_slam_toolbox|cartographer_node' >/dev/null 2>&1; then
  echo "== 1. SLAM is running"
  if ofb_wait_topic /map 15; then ok "/map published"; else fail "no /map" "read the slam pane; is /scan alive (check_stage1.sh)?"; fi
  if P="$(ofb_python "$OFB_ROBOT_DIR/lib/ros_pose.py" --parent map --timeout 10)"; then
    ok "map -> base_link: $P (x y yaw)"
  else
    fail "no map -> base_link" "SLAM needs /scan and odom -> base_link"
  fi
  echo "== 2. Save the map"
  if "$OFB_ROBOT_DIR/save_map.sh" "$NAME" >/dev/null; then ok "saved $OUT.{pgm,yaml}"; else fail "save_map.sh failed" "read $OFB_LOG_DIR/save_map.log"; fi
else
  echo "== 1. SLAM is not running: checking the saved map only"
  info "to map: ./robot/slam.sh + ./robot/teleop.sh, then rerun this check"
fi

echo "== 3. Map file"
if [ -f "$OUT.yaml" ] && [ -f "$OUT.pgm" ]; then
  ok "$OUT.yaml and .pgm exist"
  if ofb_python "$OFB_ROBOT_DIR/lib/map_info.py" "$OUT.yaml" | sed 's/^/         /'; then :; fi
  if ofb_python "$OFB_ROBOT_DIR/lib/map_info.py" "$OUT.yaml" >/dev/null; then ok "map has enough free space"; else
    fail "map looks empty or unreadable" "drive the whole room slowly and save again"
  fi
  grep -q '^image: *'"$NAME"'.pgm' "$OUT.yaml" && ok "yaml points to $NAME.pgm (relative path)" \
    || info "yaml image path: $(grep '^image:' "$OUT.yaml")"
  cp "$OUT.yaml" "$OUT.pgm" "$OFB_LOG_DIR/" 2>/dev/null || true
else
  fail "no saved map $OUT" "./robot/save_map.sh $NAME while slam.sh runs"
fi
ofb_summary
echo "Look at the map on the laptop: scp <user>@<jetson-ip>:$OUT.pgm ./ (any image viewer opens .pgm)"
echo "Keep it in git from the laptop: copy into robot/maps/ and commit."
