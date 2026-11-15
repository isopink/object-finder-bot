# shellcheck shell=bash
# Shared environment for every robot/ script. Source it, do not run it:
#   source robot/env.sh
#
# Every value can be overridden by exporting it before sourcing, e.g.
#   LDS_MODEL=LDS-01 ROS_DOMAIN_ID=42 ./robot/bringup.sh
#
# Also defines the helpers used by the scripts: ofb_log_init, ok, fail, info,
# ofb_summary, ofb_need_ros, ofb_wait_topic.

# ---------------------------------------------------------------- paths
OFB_ROBOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OFB_REPO="$(cd "$OFB_ROBOT_DIR/.." && pwd)"
export OFB_ROBOT_DIR OFB_REPO

# objmem package from the repo (no pip install needed).
case ":${PYTHONPATH:-}:" in
  *":$OFB_REPO/src:"*) ;;
  *) export PYTHONPATH="$OFB_REPO/src${PYTHONPATH:+:$PYTHONPATH}" ;;
esac

# ---------------------------------------------------------------- robot
export TURTLEBOT3_MODEL="${TURTLEBOT3_MODEL:-waffle_pi}"
export LDS_MODEL="${LDS_MODEL:-LDS-02}"          # LDS-01 or LDS-02: read the sticker on the LiDAR
export OPENCR_PORT="${OPENCR_PORT:-/dev/ttyACM0}"
export LIDAR_PORT="${LIDAR_PORT:-/dev/ttyUSB0}"
export ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-30}"       # unique per team in the classroom
# Everything runs on the Jetson: keep DDS traffic on this machine so other
# teams' robots on the same Wi-Fi are never seen. Set to 0 to talk to a laptop.
export ROS_LOCALHOST_ONLY="${ROS_LOCALHOST_ONLY:-1}"
export PYTHONUNBUFFERED=1
export RCUTILS_COLORIZED_OUTPUT="${RCUTILS_COLORIZED_OUTPUT:-0}"

# ---------------------------------------------------------------- objmem side
export OFB_CONDA_ENV="${OFB_CONDA_ENV:-test1001}"
export OFB_WORKER_PORT="${OFB_WORKER_PORT:-8600}"
export OFB_WORKER_URL="${OFB_WORKER_URL:-http://127.0.0.1:$OFB_WORKER_PORT}"
export OFB_MAPVIEW_PORT="${OFB_MAPVIEW_PORT:-8555}"
export OFB_DETECTOR="${OFB_DETECTOR:-detectnet}"  # detectnet | yolo
export OFB_IMAGE_SOURCE="${OFB_IMAGE_SOURCE:-worker}"  # worker | ros
export OFB_MAX_VEL="${OFB_MAX_VEL:-0.15}"         # m/s cap for Nav2 (raised camera mast)
export OFB_DOCKER_IMAGE="${OFB_DOCKER_IMAGE:-ofb-humble}"
export OFB_DOCKER_NAME="${OFB_DOCKER_NAME:-ofb-humble}"

# ---------------------------------------------------------------- ROS distro
# Order: $ROS_DISTRO from the caller, then /opt/ros/<distro>, then Docker.
#   OFB_ROS_MODE=native   ROS is installed on this machine (Foxy) or we are inside the container
#   OFB_ROS_MODE=docker   ROS lives in the Humble container (robot/docker/run.sh)
#   OFB_ROS_MODE=none     no ROS found
if [ -z "${ROS_DISTRO:-}" ]; then
  for _d in foxy humble galactic iron jazzy; do
    if [ -f "/opt/ros/$_d/setup.bash" ]; then ROS_DISTRO="$_d"; break; fi
  done
  unset _d
fi
if [ -n "${ROS_DISTRO:-}" ] && [ -f "/opt/ros/$ROS_DISTRO/setup.bash" ]; then
  export ROS_DISTRO
  OFB_ROS_MODE=native
  # setup.bash reads unset variables; do not let a caller's `set -u` kill us.
  set +u
  # shellcheck disable=SC1090
  source "/opt/ros/$ROS_DISTRO/setup.bash"
  # TurtleBot3 packages built from source (install_foxy_jetson.sh, Dockerfile).
  for _ws in "${OFB_TB3_WS:-$HOME/turtlebot3_ws}" /opt/tb3_ws; do
    # shellcheck disable=SC1091
    if [ -f "$_ws/install/setup.bash" ]; then source "$_ws/install/setup.bash"; fi
  done
  unset _ws
  # objmem_ros, built by robot/build_ws.sh into a per-distro workspace.
  export OFB_WS="${OFB_WS:-$OFB_ROBOT_DIR/.ws_$ROS_DISTRO}"
  # shellcheck disable=SC1091
  if [ -f "$OFB_WS/install/setup.bash" ]; then source "$OFB_WS/install/setup.bash"
  # Fallback: built by hand in ros/ as ros/README.md describes.
  elif [ -f "$OFB_REPO/ros/install/setup.bash" ]; then source "$OFB_REPO/ros/install/setup.bash"; fi
elif command -v docker >/dev/null 2>&1 && [ ! -f /.dockerenv ]; then
  export ROS_DISTRO="${ROS_DISTRO:-humble}"
  OFB_ROS_MODE=docker
else
  OFB_ROS_MODE=none
fi
export OFB_ROS_MODE

# ---------------------------------------------------------------- logging
# ofb_log_init <name> [--no-tee]
# Creates robot/logs/<timestamp>/ (or reuses $OFB_LOG_DIR, which start_all.sh
# sets so all panes share one folder) and copies stdout/stderr to <name>.log.
ofb_log_init() {
  local name="$1" mode="${2:-}"
  if [ -z "${OFB_LOG_DIR:-}" ]; then
    OFB_LOG_DIR="$OFB_ROBOT_DIR/logs/$(date +%Y%m%d_%H%M%S)"
  fi
  export OFB_LOG_DIR
  mkdir -p "$OFB_LOG_DIR"
  OFB_LOG_FILE="$OFB_LOG_DIR/$name.log"
  export OFB_LOG_FILE
  if [ "$mode" != "--no-tee" ]; then
    exec > >(tee -a "$OFB_LOG_FILE") 2>&1
  fi
  echo "== $name  $(date '+%Y-%m-%d %H:%M:%S')  log: $OFB_LOG_FILE"
  echo "== ROS_DISTRO=${ROS_DISTRO:-?} mode=$OFB_ROS_MODE ROS_DOMAIN_ID=$ROS_DOMAIN_ID" \
       "LOCALHOST_ONLY=$ROS_LOCALHOST_ONLY MODEL=$TURTLEBOT3_MODEL LDS=$LDS_MODEL"
}

OFB_N_OK=0
OFB_N_FAIL=0
# ok <message>
ok()   { OFB_N_OK=$((OFB_N_OK + 1)); echo "  [OK]   $1"; }
# fail <message> [hint]
fail() {
  OFB_N_FAIL=$((OFB_N_FAIL + 1)); echo "  [FAIL] $1"
  if [ -n "${2:-}" ]; then echo "         hint: $2"; fi
}
info() { echo "  [..]   $*"; }
# check <message> <hint> <command...>: OK if the command succeeds.
check() {
  local msg="$1" hint="$2"; shift 2
  if "$@" >/dev/null 2>&1; then ok "$msg"; else fail "$msg" "$hint"; fi
}
# ofb_summary: print the totals; exit status 1 if anything failed.
ofb_summary() {
  echo "== Result: $OFB_N_OK OK, $OFB_N_FAIL FAIL   (log: ${OFB_LOG_FILE:-none})"
  if [ "$OFB_N_FAIL" -eq 0 ]; then echo "[OK] all checks passed"; return 0; fi
  echo "[FAIL] $OFB_N_FAIL check(s) failed; read the hints above"; return 1
}

# ofb_need_ros "$0" "$@": make sure `ros2` works here. In Docker mode the
# calling script is re-run inside the Humble container (the repo is mounted at
# the same path), so every script works the same with Foxy and with Humble.
ofb_need_ros() {
  if [ "$OFB_ROS_MODE" = native ] && command -v ros2 >/dev/null 2>&1; then
    if [ -n "${CONDA_PREFIX:-}" ] && [ "${OFB_ALLOW_CONDA:-0}" != 1 ]; then
      echo "  [..]   conda env '${CONDA_DEFAULT_ENV:-?}' is active; ROS uses the system python3." \
           "If ROS commands fail, run 'conda deactivate' first."
    fi
    return 0
  fi
  if [ "$OFB_ROS_MODE" = docker ]; then
    local script; script="$(cd "$(dirname "$1")" && pwd)/$(basename "$1")"; shift
    echo "== no ROS on this machine: running inside the $OFB_DOCKER_NAME container"
    exec "$OFB_ROBOT_DIR/docker/run.sh" exec "$script" "$@"
  fi
  echo "[FAIL] ROS 2 not found (no /opt/ros/*, no docker)."
  echo "       hint: Foxy: ./robot/install_foxy_jetson.sh   Humble: ./robot/docker/run.sh build"
  exit 1
}

# ofb_wait_topic <topic> <timeout_s>: succeed when one message arrives.
# (`ros2 topic echo --once` is not in every distro; head -n 1 works everywhere.)
ofb_wait_topic() {
  local topic="$1" t="${2:-10}"
  timeout "$t" ros2 topic echo "$topic" 2>/dev/null | head -n 1 | grep -q .
}

# ofb_topic_hz <topic> <seconds>: print the average rate (or nothing).
ofb_topic_hz() {
  timeout "${2:-5}" ros2 topic hz "$1" 2>/dev/null | awk '/average rate/ {r=$3} END {if (r) print r}'
}

# ofb_make_config <depth|nodepth>: write $OFB_LOG_DIR/config_<mode>.yaml and print its path.
# Source file, first that exists: $OFB_CONFIG, robot/config/<mode>.yaml
# (your classroom measurements), config/default.yaml. camera_mode is forced to <mode>.
ofb_make_config() {
  local mode="$1" src out
  for src in "${OFB_CONFIG:-}" "$OFB_ROBOT_DIR/config/$mode.yaml" "$OFB_REPO/config/default.yaml"; do
    if [ -n "$src" ] && [ -f "$src" ]; then break; fi
  done
  mkdir -p "${OFB_LOG_DIR:?call ofb_log_init first}"
  out="$OFB_LOG_DIR/config_$mode.yaml"
  {
    echo "# generated by robot/env.sh from $src"
    sed -E "s/^camera_mode:.*/camera_mode: $mode/" "$src"
  } > "$out"
  grep -q '^camera_mode:' "$out" || echo "camera_mode: $mode" >> "$out"
  echo "$out"
}

# ofb_camera_for <depth|nodepth>: camera kind for scripts/vision_worker.py --camera.
ofb_camera_for() {
  case "$1" in depth) echo realsense ;; nodepth) echo c920 ;; *) return 1 ;; esac
}

# ofb_conda_activate: find conda and activate $OFB_CONDA_ENV (PyTorch with CUDA).
# Returns 1 with a message if conda or the env is missing. Leaves `set -u` off.
ofb_conda_activate() {
  set +u
  local base
  if ! command -v conda >/dev/null 2>&1; then
    for base in "$HOME/miniconda3" "$HOME/miniforge3" "$HOME/mambaforge" "$HOME/anaconda3" "$HOME/archiconda3"; do
      if [ -f "$base/etc/profile.d/conda.sh" ]; then
        # shellcheck disable=SC1091
        source "$base/etc/profile.d/conda.sh"; break
      fi
    done
  fi
  if ! command -v conda >/dev/null 2>&1; then
    fail "conda not found" "the worker needs the conda env with PyTorch; put conda on PATH (conda init bash)"
    return 1
  fi
  # shellcheck disable=SC1091
  source "$(conda info --base)/etc/profile.d/conda.sh"
  if ! conda activate "$OFB_CONDA_ENV" 2>/dev/null; then
    fail "conda env $OFB_CONDA_ENV not found" "conda env list; then OFB_CONDA_ENV=<name>"
    return 1
  fi
  return 0
}

# ofb_python: the system python3 that matches ROS (not conda's).
ofb_python() {
  if [ -x /usr/bin/python3 ]; then /usr/bin/python3 "$@"; else python3 "$@"; fi
}
