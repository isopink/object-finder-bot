#!/usr/bin/env bash
# Four-key teleop for mapping: w straight, d right 90, a left 90, s stop (q quit).
# Close the stock teleop.sh first (two publishers on /cmd_vel fight each other).
set -uo pipefail
source "$(dirname "$0")/env.sh"
ofb_need_ros "$0" "$@"
exec /usr/bin/python3 "$(dirname "$0")/lib/teleop4.py"
