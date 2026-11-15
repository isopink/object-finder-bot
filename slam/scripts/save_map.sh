#!/usr/bin/env bash
# Save the map from another terminal while SLAM is running. Output: maps/<name>.pgm, maps/<name>.yaml
# Usage: ./save_map.sh [name]
set -eo pipefail
source "$(dirname "$0")/env.sh"

NAME="${1:-map_$(date +%Y%m%d_%H%M%S)}"
ros2 run nav2_map_server map_saver_cli -f "$SLAM_DIR/maps/$NAME"
echo "Saved: $SLAM_DIR/maps/$NAME.{pgm,yaml}"
