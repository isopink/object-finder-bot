#!/usr/bin/env bash
# Save the current SLAM map to robot/maps/<name>.pgm and .yaml (slam.sh must be running).
# Safe to run several times while mapping; each run overwrites <name>.
#
# Usage: ./robot/save_map.sh <name>        e.g. ./robot/save_map.sh room429
set -uo pipefail
source "$(dirname "$0")/env.sh"
ofb_need_ros "$0" "$@"
ofb_log_init save_map

NAME="${1:-}"
if [ -z "$NAME" ]; then
  echo "usage: $0 <name>   (letters, digits, _ and -)"; exit 2
fi
case "$NAME" in
  *[!A-Za-z0-9_-]*) echo "[FAIL] map name '$NAME': use letters, digits, _ and - only"; exit 2 ;;
esac
OUT="$OFB_ROBOT_DIR/maps/$NAME"
mkdir -p "$OFB_ROBOT_DIR/maps"

if ofb_wait_topic /map 10; then ok "/map is published"; else
  fail "no /map" "start ./robot/slam.sh (and bringup.sh) first"; ofb_summary; exit 1
fi
# Keep the previous save as <name>.bak.* in case this one fails half-way.
for ext in yaml pgm; do
  if [ -f "$OUT.$ext" ]; then mv -f "$OUT.$ext" "$OUT.bak.$ext"; fi
done
timeout 60 ros2 run nav2_map_server map_saver_cli -f "$OUT"
if [ -f "$OUT.yaml" ] && [ -f "$OUT.pgm" ]; then
  ok "saved $OUT.pgm and $OUT.yaml"
  ofb_python "$OFB_ROBOT_DIR/lib/map_info.py" "$OUT.yaml" | sed 's/^/         /'
  cp "$OUT.yaml" "$OUT.pgm" "$OFB_LOG_DIR/" 2>/dev/null || true
else
  fail "map files not written" "is slam.sh still running? retry; the previous save is $OUT.bak.{yaml,pgm}"
fi
ofb_summary
echo "Copy to the laptop: scp -r <user>@<jetson-ip>:$OFB_ROBOT_DIR/maps ./"
