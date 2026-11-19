#!/usr/bin/env bash
# Start the objmem ROS nodes (observer, finder, mapview) once Nav2 and the
# vision worker are up. start_all.sh runs this in its own pane.
#
# Usage: ./robot/objmem.sh <map> depth|nodepth
#   OFB_INIT_POSE="x y yaw"  initial pose sent to AMCL first (default "0 0 0";
#                            set OFB_INIT_POSE=skip if you set it yourself)
#   OFB_MEMORY_FILE=path     memory file (default robot/memory/<map>_<mode>.npz;
#                            kept across runs, delete it to start empty)
#   OFB_SEARCH_LOG=path      search log (default robot/memory/search_<map>_<mode>.jsonl,
#                            read by scripts/evaluate.py)
set -uo pipefail
source "$(dirname "$0")/env.sh"
ofb_need_ros "$0" "$@"
ofb_log_init objmem

MAP="${1:-}"; MODE="${2:-}"
case "$MODE" in depth|nodepth) ;; *) echo "usage: $0 <map> depth|nodepth"; exit 2 ;; esac
MAP_NAME="$(basename "$MAP" .yaml)"
MAP_YAML="$MAP"
case "$MAP_YAML" in *.yaml) ;; *) MAP_YAML="$OFB_ROBOT_DIR/maps/$MAP.yaml" ;; esac
if [ ! -f "$MAP_YAML" ]; then MAP_YAML=""; fi
MEM="${OFB_MEMORY_FILE:-$OFB_ROBOT_DIR/memory/${MAP_NAME}_$MODE.npz}"
SEARCH_LOG="${OFB_SEARCH_LOG:-$OFB_ROBOT_DIR/memory/search_${MAP_NAME}_$MODE.jsonl}"
mkdir -p "$(dirname "$MEM")"
CONFIG="$(ofb_make_config "$MODE")"

echo "== Waiting for Nav2 (/navigate_to_pose, up to 120 s)"
for _ in $(seq 60); do
  if ros2 action list 2>/dev/null | grep -x /navigate_to_pose >/dev/null; then break; fi
  sleep 2
done
if ros2 action list 2>/dev/null | grep -x /navigate_to_pose >/dev/null; then ok "Nav2 is up"; else
  fail "Nav2 did not come up" "read the nav pane / nav.log in $OFB_LOG_DIR"
fi

INIT="${OFB_INIT_POSE:-0 0 0}"
if [ "$INIT" != skip ]; then
  # shellcheck disable=SC2086
  if "$OFB_ROBOT_DIR/set_initial_pose.sh" $INIT; then ok "initial pose $INIT"; else
    fail "initial pose not set" "run ./robot/set_initial_pose.sh x y yaw yourself"
  fi
fi

echo "== Waiting for the vision worker ($OFB_WORKER_URL/health, up to 300 s: CLIP loads first)"
for _ in $(seq 150); do
  if curl -sf -m 2 "$OFB_WORKER_URL/health" >/dev/null 2>&1; then break; fi
  sleep 2
done
if H="$(curl -sf -m 2 "$OFB_WORKER_URL/health")"; then ok "worker: $H"; else
  fail "worker not answering" "read the worker pane / worker.log in $OFB_LOG_DIR"
fi

if ros2 pkg prefix objmem_ros >/dev/null 2>&1; then ok "objmem_ros found"; else
  fail "objmem_ros not built" "./robot/build_ws.sh"
fi
if [ "$OFB_N_FAIL" -gt 0 ]; then ofb_summary; echo "Fix the above, then rerun: $0 $*"; exit 1; fi

echo "== ros2 launch objmem_ros objmem.launch.py (memory $MEM, search log $SEARCH_LOG)"
echo "   map view: http://<jetson-ip>:$OFB_MAPVIEW_PORT    queries: the ask pane"
ros2 launch objmem_ros objmem.launch.py \
  config:="$CONFIG" memory_file:="$MEM" image_source:="$OFB_IMAGE_SOURCE" \
  worker_url:="$OFB_WORKER_URL" map_yaml:="$MAP_YAML" search_log:="$SEARCH_LOG"
