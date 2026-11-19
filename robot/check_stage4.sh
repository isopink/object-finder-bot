#!/usr/bin/env bash
# Stage 4: camera and vision worker, for one or both camera versions.
# No ROS needed. If no worker is running, this starts one, tests it, and stops it.
#
# Usage: ./robot/check_stage4.sh depth|nodepth|both [--fake]
#   depth    RealSense (color + aligned depth): detections must carry depth_m
#   nodepth  Logitech C920 (color only): depth_m must be null
#   both     depth, then nodepth (plug in both cameras)
#   --fake   fake camera/detector/CLIP: tests only the HTTP path
#   OFB_DETECTOR=yolo ./robot/check_stage4.sh depth   to test YOLO
set -uo pipefail
source "$(dirname "$0")/env.sh"
ofb_log_init check_stage4

WHICH="${1:-}"; FAKE="${2:-}"
case "$WHICH" in
  depth|nodepth) MODES=("$WHICH") ;;
  both) MODES=(depth nodepth) ;;
  *) echo "usage: $0 depth|nodepth|both [--fake]"; exit 2 ;;
esac

echo "== 1. Cameras (lsusb, /dev/video*)"
USB="$(lsusb 2>/dev/null || true)"
for m in "${MODES[@]}"; do
  if [ "$FAKE" = --fake ]; then break; fi
  if [ "$m" = depth ]; then
    if grep -qi '8086:' <<<"$USB"; then ok "RealSense: $(grep -i '8086:' <<<"$USB" | head -n 1 | cut -d' ' -f6-)"; else
      fail "no RealSense on USB" "use a USB 3 port and the USB 3 cable (blue port); lsusb | grep 8086"
    fi
    if lsusb -t 2>/dev/null | grep -i 'uvcvideo' | grep '5000M' >/dev/null; then ok "a UVC device runs at USB 3 speed (5000M)"; else
      info "no UVC device at 5000M: RealSense on USB 2 limits depth resolution and fps"
    fi
  else
    if grep -qi '046d:08' <<<"$USB"; then ok "Logitech C920: $(grep -i '046d:08' <<<"$USB" | head -n 1 | cut -d' ' -f6-)"; else
      fail "no Logitech camera on USB" "plug in the C920; lsusb | grep 046d"
    fi
  fi
done
info "video devices: $(ls /dev/video* 2>/dev/null | tr '\n' ' ')"
if command -v v4l2-ctl >/dev/null 2>&1; then v4l2-ctl --list-devices 2>/dev/null | sed 's/^/         /'; fi

echo "== 2. Memory"
free -m | sed 's/^/         /'
AVAIL="$(free -m | awk '/^Mem:/ {print $7}')"
if curl -sf -m 2 "$OFB_WORKER_URL/health" >/dev/null 2>&1; then
  info "a worker is already running and holds its memory; it will be reused (no new 2 GB needed)"
elif [ -n "$AVAIL" ] && [ "$AVAIL" -lt 1500 ]; then
  fail "only ${AVAIL} MB available" "close other programs (vision/find_object.py, old workers); CLIP + detector need ~2 GB"
fi

echo "== 3. Python packages (conda env $OFB_CONDA_ENV)"
if ofb_conda_activate; then
  ok "conda env $OFB_CONDA_ENV: $(command -v python)"
  for m in "${MODES[@]}"; do
    DET="$OFB_DETECTOR"; [ "$FAKE" = --fake ] && DET=fake
    if python "$OFB_ROBOT_DIR/lib/env_probe.py" "$m" "$DET"; then ok "packages for $m / $DET"; else
      fail "packages for $m / $DET" "see the lines above"
    fi
  done
  conda deactivate 2>/dev/null || true
fi

for m in "${MODES[@]}"; do
  echo "== 4. Vision worker, $m mode"
  STARTED=""
  if curl -sf -m 2 "$OFB_WORKER_URL/health" >/dev/null 2>&1; then
    info "using the worker already running on $OFB_WORKER_URL"
  else
    info "starting ./robot/worker.sh $m $FAKE (log: $OFB_LOG_DIR/worker.log)"
    # setsid: own process group, so the whole worker stops at the end.
    setsid "$OFB_ROBOT_DIR/worker.sh" "$m" $FAKE >/dev/null 2>&1 < /dev/null &
    STARTED=$!
    # Ctrl+C on this check must not leave the worker (~3 GB) running.
    trap 'kill -INT -- "-$STARTED" 2>/dev/null; sleep 2; kill -- "-$STARTED" 2>/dev/null; exit 130' INT TERM
  fi
  T0=$(date +%s)
  if ofb_python "$OFB_ROBOT_DIR/lib/worker_probe.py" --url "$OFB_WORKER_URL" --mode "$m" --n 5 --wait 300; then
    ok "worker in $m mode (first answer after $(( $(date +%s) - T0 )) s)"
  else
    fail "worker in $m mode" "read $OFB_LOG_DIR/worker.log (camera not found? CUDA out of memory? missing package?)"
  fi
  if [ -n "$STARTED" ]; then
    kill -INT -- "-$STARTED" 2>/dev/null || kill -INT "$STARTED" 2>/dev/null
    sleep 3
    kill -- "-$STARTED" 2>/dev/null || true
    wait "$STARTED" 2>/dev/null || true
    trap - INT TERM
    info "stopped the worker started by this check"
    sleep 2
  fi
done

ofb_summary
echo "Copy back: scp -r <user>@<jetson-ip>:$OFB_LOG_DIR ./"
