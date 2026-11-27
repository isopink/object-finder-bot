#!/usr/bin/env bash
# Localize on a saved map (AMCL) and start Nav2. bringup.sh must be running;
# slam.sh must NOT be running. Leave it running; stop with Ctrl+C.
#
# Usage: ./robot/nav.sh <map>        <map> = robot/maps/<map>.yaml, or a path to a .yaml
# Then:  ./robot/set_initial_pose.sh x y yaw   (where the robot stands on the map)
#        ./robot/goto.sh x y yaw              (one goal)
#
# Parameters: the TurtleBot3 Nav2 file for waffle_pi, copied into the log
# folder with the forward speed capped at OFB_MAX_VEL (default 0.15 m/s).
# Use your own file with NAV2_PARAMS=/path/to/params.yaml.
set -uo pipefail
source "$(dirname "$0")/env.sh"
ofb_need_ros "$0" "$@"
ofb_log_init nav

ARG="${1:-}"
if [ -z "$ARG" ]; then
  echo "usage: $0 <map>     maps: $(cd "$OFB_ROBOT_DIR/maps" 2>/dev/null && ls -- *.yaml 2>/dev/null | sed 's/\.yaml$//' | tr '\n' ' ')"
  exit 2
fi
MAP="$ARG"
case "$MAP" in *.yaml) ;; *) MAP="$OFB_ROBOT_DIR/maps/$MAP.yaml" ;; esac
MAP="$(cd "$(dirname "$MAP")" 2>/dev/null && pwd)/$(basename "$MAP")"

echo "== Checks"
if [ -f "$MAP" ]; then ok "map $MAP"; else
  fail "no map file $MAP" "make one: ./robot/slam.sh then ./robot/save_map.sh <name>"
fi
if ofb_wait_topic /scan 10; then ok "/scan"; else fail "no /scan" "start ./robot/bringup.sh first"; fi
if pgrep -f 'async_slam_toolbox|sync_slam_toolbox|cartographer_node' >/dev/null 2>&1; then
  fail "SLAM is still running" "Ctrl+C slam.sh first (SLAM and AMCL both publish map->odom)"
fi

PARAMS="${NAV2_PARAMS:-}"
# Foxy: the apt turtlebot3_navigation2 waffle_pi.yaml is in the old layout
# (dwb_controller, no FollowPath section), so nav2 0.4.7's controller_server ran with
# empty limits ("No valid trajectories out of 0") and bt_navigator aborted every goal
# (2026-11-27). robot/config/nav2_foxy_waffle_pi.yaml is nav2_bringup's own params
# file with xy_goal_tolerance 0.10 and a minimal behavior tree; it drove 1 m and back.
if [ -z "$PARAMS" ] && [ "${ROS_DISTRO:-}" = foxy ] && [ -f "$OFB_ROBOT_DIR/config/nav2_foxy_waffle_pi.yaml" ]; then
  PARAMS="$OFB_ROBOT_DIR/config/nav2_foxy_waffle_pi.yaml"
fi
if [ -z "$PARAMS" ]; then
  TB3_NAV="$(ros2 pkg prefix turtlebot3_navigation2 2>/dev/null)/share/turtlebot3_navigation2/param"
  for cand in "$TB3_NAV/$ROS_DISTRO/$TURTLEBOT3_MODEL.yaml" "$TB3_NAV/$TURTLEBOT3_MODEL.yaml"; do
    if [ -f "$cand" ]; then PARAMS="$cand"; break; fi
  done
fi
if [ -n "$PARAMS" ] && [ -f "$PARAMS" ]; then
  ok "Nav2 params $PARAMS"
  # Cap the forward speed (raised camera = top-heavy robot).
  sed -E \
    -e "s/^([[:space:]]*max_vel_x:[[:space:]]*)[0-9.]+/\1$OFB_MAX_VEL/" \
    -e "s/^([[:space:]]*max_speed_xy:[[:space:]]*)[0-9.]+/\1$OFB_MAX_VEL/" \
    -e "s/^([[:space:]]*max_velocity:[[:space:]]*)\[[[:space:]]*[0-9.]+/\1[$OFB_MAX_VEL/" \
    -e "s#@OFB_CONFIG_DIR@#$OFB_ROBOT_DIR/config#g" \
    "$PARAMS" > "$OFB_LOG_DIR/nav2_params.yaml"
  PARAMS="$OFB_LOG_DIR/nav2_params.yaml"
  info "speed cap $OFB_MAX_VEL m/s -> $PARAMS"
else
  fail "Nav2 params file not found" "install ros-$ROS_DISTRO-turtlebot3-navigation2, or set NAV2_PARAMS"
fi
if [ "$OFB_N_FAIL" -gt 0 ]; then ofb_summary; exit 1; fi
cp "$MAP" "$OFB_LOG_DIR/" 2>/dev/null || true

# With the four-command navigator (OFB_NAV4=1, the default) only the map server and AMCL are
# needed. Nav2's planner and controller were never asked for anything and still used 96 % and
# 68 % of a core for their costmaps (measured 2026-11-27, 6 cores, load average 7 to 9).
# OFB_NAV_FULL=1 starts all of Nav2 again (needed for goto.sh, patrol.sh, OFB_NAV4=0).
if [ "${OFB_NAV4:-1}" = 1 ] && [ "${OFB_NAV_FULL:-0}" != 1 ]; then
  echo "== Starting the map server and AMCL only on $(basename "$MAP") (four-command navigation)."
  ros2 launch nav2_bringup localization_launch.py \
    map:="$MAP" params_file:="$PARAMS" use_sim_time:=False autostart:=True
else
  echo "== Starting AMCL + Nav2 on $(basename "$MAP"). Next, in another pane:"
  echo "     ./robot/set_initial_pose.sh 0 0 0    (if the robot stands where mapping started)"
  ros2 launch nav2_bringup bringup_launch.py \
    map:="$MAP" params_file:="$PARAMS" use_sim_time:=False autostart:=True
fi
