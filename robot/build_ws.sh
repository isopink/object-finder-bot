#!/usr/bin/env bash
# Build the objmem_ros package (ros/objmem_ros) with colcon. Run again after a
# `git pull` that changes ros/ (setup.py, launch files, new entry points).
# Output goes to robot/.ws_<distro>/ (not tracked), sourced by robot/env.sh.
#
# Usage: ./robot/build_ws.sh            (Foxy native, or Humble: runs in the container)
set -uo pipefail
source "$(dirname "$0")/env.sh"
ofb_need_ros "$0" "$@"
ofb_log_init build_ws

if [ -n "${CONDA_PREFIX:-}" ]; then
  fail "conda env '$CONDA_DEFAULT_ENV' is active" "run 'conda deactivate' so colcon uses the system python3"
  ofb_summary; exit 1
fi
if [ ! -d "$OFB_REPO/ros" ]; then
  fail "no ros/ folder in $OFB_REPO" "git pull; objmem_ros lives in ros/objmem_ros"
  ofb_summary; exit 1
fi
check "colcon available" "sudo apt install python3-colcon-common-extensions" command -v colcon

mkdir -p "$OFB_WS"
if colcon --log-base "$OFB_WS/log" build --symlink-install \
     --base-paths "$OFB_REPO/ros" \
     --build-base "$OFB_WS/build" --install-base "$OFB_WS/install"; then
  ok "colcon build in $OFB_WS"
else
  fail "colcon build failed" "read the error above; ros/README.md has the package details"
fi
# shellcheck disable=SC1091
set +u; source "$OFB_WS/install/setup.bash"; set -u
check "ros2 can find objmem_ros" "the package name in ros/objmem_ros/package.xml must be objmem_ros" \
  ros2 pkg prefix objmem_ros
check "python can import objmem" "PYTHONPATH must contain $OFB_REPO/src (robot/env.sh sets it)" \
  ofb_python -c "import objmem"
ofb_summary
