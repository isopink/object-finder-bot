#!/usr/bin/env bash
# Run one ROS command with robot/env.sh sourced: natively (Foxy) or inside the
# Humble container. Used by start_all.sh for raw ros2 commands.
#
# Usage: robot/lib/ros_exec.sh ros2 run objmem_ros ask
set -uo pipefail
source "$(dirname "$0")/../env.sh"
ofb_need_ros "$0" "$@"
exec "$@"
