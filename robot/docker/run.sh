#!/usr/bin/env bash
# ROS 2 Humble in Docker on the Jetson (use when the robot side must be Humble).
# The container shares the host network (ROS topics, ports 8554/8555/8600),
# sees /dev (OpenCR, LiDAR, cameras), and mounts this repo at the same path, so
# every robot/*.sh script works the same inside and outside.
#
# Usage:
#   ./robot/docker/run.sh build          build the image (once, 20-40 min on the Jetson)
#   ./robot/docker/run.sh                open a shell in the container (starts it if needed)
#   ./robot/docker/run.sh exec <cmd...>  run one command in the container, with robot/env.sh sourced
#   ./robot/docker/run.sh status         is the container running?
#   ./robot/docker/run.sh stop           stop and remove the container
#
# Scripts that need ROS call this automatically when /opt/ros is missing on
# the host (see ofb_need_ros in robot/env.sh).
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
IMAGE="${OFB_DOCKER_IMAGE:-ofb-humble}"
NAME="${OFB_DOCKER_NAME:-ofb-humble}"
DOCKER="docker"
if ! docker info >/dev/null 2>&1; then DOCKER="sudo docker"; fi

# Variables copied into every `exec`, so the host's choices reach the container.
PASS_VARS=(ROS_DOMAIN_ID ROS_LOCALHOST_ONLY TURTLEBOT3_MODEL LDS_MODEL OPENCR_PORT LIDAR_PORT
           OFB_LOG_DIR OFB_MAX_VEL OFB_IMAGE_SOURCE OFB_WORKER_URL OFB_WORKER_PORT
           OFB_MAPVIEW_PORT OFB_DETECTOR OFB_BAG_STORAGE OFB_CONFIG OFB_MEMORY_FILE NAV2_PARAMS TERM)

running() { [ "$($DOCKER inspect -f '{{.State.Running}}' "$NAME" 2>/dev/null)" = true ]; }

start() {
  if running; then return 0; fi
  if ! $DOCKER image inspect "$IMAGE" >/dev/null 2>&1; then
    echo "[FAIL] image $IMAGE not built"
    echo "       hint: ./robot/docker/run.sh build"
    exit 1
  fi
  $DOCKER rm -f "$NAME" >/dev/null 2>&1 || true
  mkdir -p "$REPO/robot/.docker_home"
  # --privileged + /dev: USB devices can be unplugged and replugged while it runs.
  # --user: files written into the repo (maps, logs, bags) stay owned by you.
  if $DOCKER run -d --name "$NAME" \
      --network host --ipc host --pid host --privileged \
      -v /dev:/dev -v /run/udev:/run/udev:ro \
      -v "$REPO:$REPO" -w "$REPO" \
      --user "$(id -u):$(id -g)" --group-add dialout --group-add video \
      -e HOME="$REPO/robot/.docker_home" -e OFB_REPO="$REPO" -e ROS_DISTRO=humble \
      "$IMAGE" sleep infinity >/dev/null; then
    echo "[OK]   container $NAME started (image $IMAGE)"
  else
    echo "[FAIL] could not start container $NAME"
    echo "       hint: is docker running? 'sudo systemctl start docker'; try '$DOCKER logs $NAME'"
    exit 1
  fi
}

exec_in() {
  start
  local flags=(-i)
  if [ -t 0 ] && [ -t 1 ]; then flags=(-it); fi
  local v
  for v in "${PASS_VARS[@]}"; do
    if [ -n "${!v:-}" ]; then flags+=(-e "$v=${!v}"); fi
  done
  local wd="$REPO"
  case "$PWD/" in "$REPO"/*) wd="$PWD" ;; esac
  # shellcheck disable=SC2016
  exec $DOCKER exec "${flags[@]}" -w "$wd" "$NAME" \
    bash -c 'set +u; source "$OFB_REPO/robot/env.sh"; exec "$@"' ofb "$@"
}

case "${1:-shell}" in
  build)
    $DOCKER build -t "$IMAGE" "$HERE" && echo "[OK]   image $IMAGE built" \
      || { echo "[FAIL] docker build failed"; echo "       hint: check the network (apt, github) and disk space (df -h)"; exit 1; }
    ;;
  shell)
    exec_in bash
    ;;
  exec)
    shift
    [ $# -gt 0 ] || { echo "usage: $0 exec <command...>"; exit 2; }
    exec_in "$@"
    ;;
  status)
    if running; then echo "[OK]   $NAME is running"; else echo "[..]   $NAME is not running"; exit 1; fi
    ;;
  stop)
    $DOCKER rm -f "$NAME" >/dev/null 2>&1 && echo "[OK]   $NAME removed" || echo "[..]   $NAME was not running"
    ;;
  *)
    echo "usage: $0 [build|shell|exec <cmd...>|status|stop]"; exit 2
    ;;
esac
