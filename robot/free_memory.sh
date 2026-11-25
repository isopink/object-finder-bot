#!/usr/bin/env bash
# Show where the Jetson's memory goes and PRINT (never run) the sudo commands that
# free about 500 MB for the full system (bringup + Nav2 + vision worker + objmem).
# Run it, read the checks, then copy the commands you agree with. Nothing here
# changes the system: it only reads /proc, systemctl and dpkg.
#
# Usage: ./robot/free_memory.sh
#
# Why each service can go (checked on the Jetson, 2026-11-25; see robot/README.md,
# "Freeing memory"):
#   GUI (gdm, gnome-shell, Xorg, ~270 MB): we only use SSH and tmux; the scripts run
#     no RViz or other window (slam.sh / replay.sh pass use_rviz:=False).
#   docker + containerd (~120 MB): the robot runs ROS 2 Foxy natively (~/.bashrc
#     sources /opt/ros/foxy). robot/docker/ (Humble) is only the fallback plan.
#   mongodb (~117 MB): installed as a dependency of ros-foxy-warehouse-ros-mongo
#     (MoveIt warehouse, from turtlebot3_manipulation). Nothing here uses MoveIt or MongoDB; its data
#     directory is 288 KB (empty database).
set -uo pipefail

say() { printf '%s\n' "$*"; }
kb_to_mb() { awk -v k="$1" 'BEGIN { printf "%d", k / 1024 }'; }
meminfo() { awk -v k="$1:" '$1 == k { print $2 }' /proc/meminfo; }

say "== Memory now"
if [ -r /proc/meminfo ]; then
  for k in MemTotal MemFree MemAvailable Cached CmaFree; do
    v="$(meminfo "$k")"
    [ -n "$v" ] && printf '  %-13s %6s MB\n' "$k" "$(kb_to_mb "$v")"
  done
  say "  (GPU memory cannot use the page cache: watch MemFree, not MemAvailable."
  say "   ./robot/lib/drop_cache.py empties the cache without root.)"
else
  say "  /proc/meminfo not readable (not Linux?)"
fi

say ""
say "== Largest processes (RSS)"
ps -eo rss=,comm= --sort=-rss 2>/dev/null | head -12 | awk '{ printf "  %6d MB  %s\n", $1 / 1024, $2 }'

say ""
say "== Services"
unit_state() {
  local u="$1" en act
  en="$(systemctl is-enabled "$u" 2>/dev/null)"; en="${en:-absent}"
  act="$(systemctl is-active "$u" 2>/dev/null)"; act="${act:-unknown}"
  printf '  %-12s enabled=%-9s active=%s\n' "$u" "$en" "$act"
}
if command -v systemctl >/dev/null 2>&1; then
  say "  boot target: $(systemctl get-default 2>/dev/null)"
  for u in gdm3 gdm docker containerd mongodb; do unit_state "$u"; done
else
  say "  no systemctl here"
fi
if command -v dpkg >/dev/null 2>&1; then
  # mongodb was pulled in by ros-foxy-warehouse-ros-mongo (MoveIt, for the
  # turtlebot3_manipulation arm); none of it runs in this project.
  pk="$(dpkg -l 2>/dev/null | awk '$1 == "ii" && $2 ~ /mongo/ { print $2 }' | tr '\n' ' ')"
  nm="$(dpkg -l 2>/dev/null | awk '$1 == "ii" && $2 ~ /moveit/' | wc -l)"
  [ -n "$pk" ] && say "  mongo packages: $pk"
  [ "$nm" -gt 0 ] && say "  moveit packages: $nm (unused here; they are why mongodb is installed)"
fi

cat <<'EOF'

== Commands to run yourself (only when no one is mapping or driving)
Check first:
  sudo docker ps -a; sudo docker images      # nothing we need? (Humble image unused)
  grep -rn -i mongo ~/turtlebot3_ws/src 2>/dev/null | head   # expect nothing

Then:
  sudo systemctl set-default multi-user.target    # boot without the desktop (~270 MB); needs a reboot
  sudo systemctl disable --now docker.socket docker containerd   # ~120 MB
  sudo systemctl disable --now mongodb            # ~117 MB
  sudo reboot

Undo:
  sudo systemctl set-default graphical.target
  sudo systemctl enable --now containerd docker.socket docker mongodb

After the reboot, measure again with ./robot/free_memory.sh and write the numbers
in docs/lab/트러블슈팅_기록.md.
EOF
