#!/usr/bin/env bash
# Start the whole system in one tmux session "ofb":
#   bringup | nav (AMCL + Nav2) | vision worker (conda) | objmem nodes | ask
# (plus a camera pane when OFB_IMAGE_SOURCE=ros). Run on the Jetson host, not
# in Docker; ROS panes enter the Humble container by themselves when needed.
#
# Usage: ./robot/start_all.sh <map> [depth|nodepth]
#   <map>  name in robot/maps/ (without .yaml) or a path to a .yaml
#   Place the robot where mapping started, facing the same way, or set
#   OFB_INIT_POSE="x y yaw". Then: tmux attach -t ofb
#
# Inside tmux: Ctrl+B then arrow keys moves between panes, Ctrl+B z zooms one
# pane, Ctrl+B d detaches (everything keeps running). Stop: ./robot/stop_all.sh
set -uo pipefail
source "$(dirname "$0")/env.sh"
OFB_LOG_DIR="$OFB_ROBOT_DIR/logs/$(date +%Y%m%d_%H%M%S)_all"
ofb_log_init start_all

MAP="${1:-}"; MODE="${2:-depth}"
SESSION="${OFB_TMUX_SESSION:-ofb}"
if [ -z "$MAP" ]; then
  echo "usage: $0 <map> [depth|nodepth]"
  echo "maps: $(cd "$OFB_ROBOT_DIR/maps" 2>/dev/null && ls -- *.yaml 2>/dev/null | sed 's/\.yaml$//' | tr '\n' ' ')"
  exit 2
fi
case "$MODE" in depth|nodepth) ;; *) echo "camera mode must be depth or nodepth"; exit 2 ;; esac
MAP_FILE="$MAP"
case "$MAP_FILE" in *.yaml) ;; *) MAP_FILE="$OFB_ROBOT_DIR/maps/$MAP.yaml" ;; esac

echo "== Checks"
check "tmux installed" "sudo apt install tmux" command -v tmux
if [ -f "$MAP_FILE" ]; then ok "map $MAP_FILE"; else fail "no map $MAP_FILE" "./robot/slam.sh then ./robot/save_map.sh <name>"; fi
case "$OFB_ROS_MODE" in
  native) ok "ROS $ROS_DISTRO native" ;;
  # Start the container once here, so the panes do not race to create it.
  docker) if "$OFB_ROBOT_DIR/docker/run.sh" exec true </dev/null; then
            ok "ROS humble in Docker ($OFB_DOCKER_NAME running)"
          else fail "Humble container did not start" "./robot/docker/run.sh build, then retry"; fi ;;
  *) fail "no ROS" "./robot/install_foxy_jetson.sh or ./robot/docker/run.sh build" ;;
esac
# After ./robot/stop_all.sh --keep-worker the session holds only the worker pane: reuse it
# (restarting the worker often fails on the Jetson GPU until the next reboot).
REUSE_WORKER=0
if tmux has-session -t "$SESSION" 2>/dev/null; then
  TITLES="$(tmux list-panes -s -t "$SESSION" -F '#{pane_title}' | tr '
' ' ')"
  HEALTH="$(curl -sf -m 3 "$OFB_WORKER_URL/health" 2>/dev/null || true)"
  if [ "$TITLES" = "worker " ] && echo "$HEALTH" | grep -q "\"camera_mode\": \"$MODE\""; then
    REUSE_WORKER=1; ok "reusing the running vision worker ($HEALTH)"
  elif [ "$TITLES" = "worker " ]; then
    fail "the kept worker does not fit (health: ${HEALTH:-no answer}, wanted camera mode $MODE)" "./robot/stop_all.sh, then retry"
  else
    fail "tmux session '$SESSION' already exists" "./robot/stop_all.sh --keep-worker first, or: tmux attach -t $SESSION"
  fi
fi
if [ "$OFB_N_FAIL" -gt 0 ]; then ofb_summary; exit 1; fi

R="$OFB_ROBOT_DIR"
# Every pane starts in the repo with the same log folder and choices.
PRE="cd '$OFB_REPO' && export OFB_LOG_DIR='$OFB_LOG_DIR' OFB_IMAGE_SOURCE='$OFB_IMAGE_SOURCE' OFB_DETECTOR='$OFB_DETECTOR' ROS_DOMAIN_ID='$ROS_DOMAIN_ID' LDS_MODEL='$LDS_MODEL' OFB_INIT_POSE='${OFB_INIT_POSE:-0 0 0}' OFB_SCAN_MIN='${OFB_SCAN_MIN:-0}' OFB_NAV4='${OFB_NAV4:-1}' OFB_TILES='${OFB_TILES:-1}' OFB_DET_THRESHOLD='${OFB_DET_THRESHOLD:-}' OFB_OWL_PROMPTS='${OFB_OWL_PROMPTS:-}' OFB_ODOM_IMU='${OFB_ODOM_IMU:-1}' OFB_DDS_WIDE='${OFB_DDS_WIDE:-0}' OFB_MAX_VEL='${OFB_MAX_VEL:-0.15}'${OFB_MEMORY_FILE:+ OFB_MEMORY_FILE='$OFB_MEMORY_FILE'}${OFB_CONFIG:+ OFB_CONFIG='$OFB_CONFIG'} &&"
# ROS panes leave conda so ROS uses the system python3.
NOCONDA="{ command -v conda >/dev/null && conda deactivate 2>/dev/null; true; } &&"

pane() {  # pane <title> <command>
  local title="$1" cmd="$2" id
  if [ -z "${FIRST_DONE:-}" ] && [ "$REUSE_WORKER" = 0 ]; then
    tmux new-session -d -s "$SESSION" -n main -x 220 -y 60
    id="$(tmux display-message -p -t "$SESSION:main" '#{pane_id}')"
    FIRST_DONE=1
  else
    id="$(tmux split-window -t "$SESSION:main" -P -F '#{pane_id}')"
    tmux select-layout -t "$SESSION:main" tiled >/dev/null
  fi
  tmux select-pane -t "$id" -T "$title" 2>/dev/null || true
  tmux send-keys -t "$id" "$PRE $cmd" C-m
  echo "  pane $title: $cmd"
}

# The worker goes first and the ROS panes wait for it (up to 7 min). With bringup and
# SLAM/Nav2 already running, the NanoOWL TensorRT engine could not allocate its GPU
# memory and every /detect_embed answered 500 (2026-11-25); loaded first, it works and
# the ROS side starts fine afterwards.
WAITW="{ timeout 420 bash -c 'until curl -sf -m 2 $OFB_WORKER_URL/health >/dev/null 2>&1; do sleep 3; done'; true; } &&"

echo "== Starting tmux session '$SESSION' (logs: $OFB_LOG_DIR)"
if [ "$REUSE_WORKER" = 1 ]; then echo "  pane worker: kept"; else pane worker  "$R/worker.sh $MODE"; fi
pane bringup "$NOCONDA $WAITW $R/bringup.sh"
pane nav     "$NOCONDA $WAITW sleep 10 && $R/nav.sh '$MAP_FILE'"
if [ "$OFB_IMAGE_SOURCE" = ros ]; then
  pane camera "$NOCONDA $WAITW $R/camera_ros.sh $MODE"
fi
pane objmem  "$NOCONDA $WAITW sleep 20 && $R/objmem.sh '$MAP_FILE' $MODE"
pane ask     "$NOCONDA $WAITW sleep 30 && echo 'Waiting for the objmem nodes; then type: q a blue mug' && $R/lib/ros_exec.sh ros2 run objmem_ros ask"
tmux set-option -t "$SESSION" pane-border-status top >/dev/null 2>&1 || true
tmux set-option -t "$SESSION" mouse on >/dev/null 2>&1 || true
tmux select-pane -t "$SESSION:main.{bottom-right}" 2>/dev/null || true

IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
ok "started"
echo
echo "  Attach:     tmux attach -t $SESSION        (Ctrl+B d to detach, everything keeps running)"
echo "  Map view:   http://${IP:-<jetson-ip>}:$OFB_MAPVIEW_PORT"
echo "  Check:      ./robot/check_stage5.sh        (after about 1-2 minutes)"
echo "  Stop:       ./robot/stop_all.sh"
echo "  Logs:       $OFB_LOG_DIR"
