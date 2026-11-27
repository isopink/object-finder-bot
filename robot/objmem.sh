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
NAV_MAP_YAML="$MAP_YAML"      # the map the four-command navigator plans on (the aisle map)
# The map view draws the full SLAM map (walls, desks) when the navigation map is the aisle-only
# copy "<name>_nav" made from it (same size and origin). OFB_VIEW_MAP=<yaml> picks another one.
VIEW_MAP="${OFB_VIEW_MAP:-${MAP_YAML%_nav.yaml}.yaml}"
if [ -n "$MAP_YAML" ] && [ -f "$VIEW_MAP" ]; then MAP_YAML="$VIEW_MAP"; fi
MEM="${OFB_MEMORY_FILE:-$OFB_ROBOT_DIR/memory/${MAP_NAME}_$MODE.npz}"
SEARCH_LOG="${OFB_SEARCH_LOG:-$OFB_ROBOT_DIR/memory/search_${MAP_NAME}_$MODE.jsonl}"
mkdir -p "$(dirname "$MEM")"
CONFIG="$(ofb_make_config "$MODE")"

if [ "${OFB_NAV4:-1}" = 1 ] && [ "${OFB_NAV_FULL:-0}" != 1 ]; then
  # nav.sh started the map server and AMCL only (no /navigate_to_pose action of Nav2)
  echo "== Waiting for AMCL (/amcl node, up to 120 s)"
  for _ in $(seq 60); do
    if ros2 node list 2>/dev/null | grep -x /amcl >/dev/null; then break; fi
    sleep 2
  done
  if ros2 node list 2>/dev/null | grep -x /amcl >/dev/null; then ok "AMCL is up"; else
    fail "AMCL did not come up" "read the nav pane / nav.log in $OFB_LOG_DIR"
  fi
  sleep 5   # the lifecycle manager activates the map server and AMCL
else
  echo "== Waiting for Nav2 (/navigate_to_pose, up to 120 s)"
  for _ in $(seq 60); do
    if ros2 action list 2>/dev/null | grep -x /navigate_to_pose >/dev/null; then break; fi
    sleep 2
  done
  if ros2 action list 2>/dev/null | grep -x /navigate_to_pose >/dev/null; then ok "Nav2 is up"; else
    fail "Nav2 did not come up" "read the nav pane / nav.log in $OFB_LOG_DIR"
  fi
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
# OFB_NAV4=1: drive to remembered objects with four commands only (straight, right 90,
# left 90, stop) instead of Nav2 curves. Nav2 keeps running for map_server + AMCL.
NAV_ACTION=navigate_to_pose
NAV_TIMEOUT=120
# OFB_START_MARK="x y": the X on the map view. Default: the tape where the robot is put down
# in room_l4 (found three times by robot/relocalize.sh on 2026-11-28; the map origin, where
# mapping started, is 0.49 m ahead of it). "none" = no mark.
[ "${OFB_START_MARK:-}" = none ] && OFB_START_MARK=" "
# OFB_OBSERVE_MOVING=1 (default since 2026-11-28): remember objects while driving straight,
# not only after stopping; frames taken while turning are skipped. 0 = only when stopped.
# OFB_OBSERVE_RATE: looks per second asked for (5.0; it was 2.0 until 2026-11-28, which gave 1.76).
# The observer waits for each worker answer, so a slow answer lowers the real rate: read it off the
# times of the "observe:" lines. How often a look counts for p is p_update_dist in robot/config/<mode>.yaml.
if [ "${OFB_OBSERVE_MOVING:-1}" = 1 ]; then
  ONLY_STOPPED=false; SKIP_TURNING=true; OBS_RATE="${OFB_OBSERVE_RATE:-5.0}"
else
  ONLY_STOPPED=true; SKIP_TURNING=false; OBS_RATE="${OFB_OBSERVE_RATE:-1.0}"
fi
echo "   observing: $([ "$ONLY_STOPPED" = true ] && echo 'only when stopped' || echo 'while driving straight and when stopped') ($OBS_RATE per second)"
if [ "${OFB_NAV4:-1}" = 1 ]; then
  NAV_ACTION=navigate_to_pose_4cmd
  NAV_TIMEOUT=240      # 9 m of aisle at 0.12 m/s is 75 s plus turns; gridnav itself stops at 220 s
  ros2 run objmem_ros gridnav --ros-args -p map_yaml:="$NAV_MAP_YAML" -p arrive_wiggle_reps:="${OFB_NAV4_WIGGLE:-3}" -p arrive_wiggle_deg:="${OFB_NAV4_WIGGLE_DEG:-15.0}" -p speed:="${OFB_NAV4_SPEED:-0.12}" -p turn_rate:="${OFB_NAV4_TURN:-0.25}" >> "$OFB_LOG_DIR/gridnav.log" 2>&1 &
  GRIDNAV_PID=$!
  trap 'kill $GRIDNAV_PID 2>/dev/null; pkill -f lib/objmem_ros/gridnav 2>/dev/null' EXIT
  echo "   four-command navigation: ON (action $NAV_ACTION, log $OFB_LOG_DIR/gridnav.log)"
fi
ros2 launch objmem_ros objmem.launch.py \
  config:="$CONFIG" memory_file:="$MEM" image_source:="$OFB_IMAGE_SOURCE" \
  worker_url:="$OFB_WORKER_URL" map_yaml:="$MAP_YAML" search_log:="$SEARCH_LOG" evidence_log:="$OFB_LOG_DIR/evidence.jsonl" nav_action:="$NAV_ACTION" nav_timeout_s:="$NAV_TIMEOUT" \
  only_when_stopped:="$ONLY_STOPPED" skip_while_turning:="$SKIP_TURNING" observe_rate:="$OBS_RATE" \
  start_mark:="${OFB_START_MARK:--0.49 -0.01}"
