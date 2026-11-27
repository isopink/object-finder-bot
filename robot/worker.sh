#!/usr/bin/env bash
# Start the vision worker (camera + detector + CLIP, HTTP on port 8600) in the
# conda env. Runs on the host, never in Docker. Leave it running; Ctrl+C stops it.
#
# Usage: ./robot/worker.sh depth|nodepth [--fake] [--camera none] [extra vision_worker.py args]
#   depth    RealSense (color + depth)       -> --camera realsense
#   nodepth  Logitech C920 (color only)      -> --camera c920
#   --fake   fake camera, detector, CLIP (tests the HTTP path, no GPU)
#   OFB_DETECTOR=yolo ./robot/worker.sh depth    to use YOLO instead of detectNet
#   OFB_DETECTOR=owl  ./robot/worker.sh depth    NanoOWL: open vocabulary (clear bottles, boxes)
#   OFB_IMAGE_SOURCE=ros: the camera belongs to a ROS node, so --camera none
set -uo pipefail
source "$(dirname "$0")/env.sh"
ofb_log_init "worker"

MODE="${1:-}"
case "$MODE" in
  depth|nodepth) shift ;;
  *) echo "usage: $0 depth|nodepth [--fake] [extra args]"; exit 2 ;;
esac
CONFIG="$(ofb_make_config "$MODE")"
ARGS=(--config "$CONFIG" --port "$OFB_WORKER_PORT")
if [ "${1:-}" = "--fake" ]; then
  shift; ARGS+=(--fake)
else
  CAM="$(ofb_camera_for "$MODE")"
  if [ "$OFB_IMAGE_SOURCE" = ros ]; then CAM=none; fi
  ARGS+=(--detector "$OFB_DETECTOR" --camera "$CAM")
fi
# Only look for one kind of object (e.g. the demo bottle): OFB_OWL_PROMPTS="a water bottle"
# (comma separated, NanoOWL), OFB_TILES=0 (no tile crops when nothing is found, so the
# memory holds only real detections), OFB_DET_THRESHOLD=0.25 (confidence, default per detector).
if [ -n "${OFB_OWL_PROMPTS:-}" ]; then ARGS+=(--owl-prompts "$OFB_OWL_PROMPTS"); fi
if [ "${OFB_TILES:-1}" = 0 ]; then ARGS+=(--no-tiles); fi
if [ -n "${OFB_DET_THRESHOLD:-}" ]; then ARGS+=(--threshold "$OFB_DET_THRESHOLD"); fi
ARGS+=("$@")

# The conda env has PyTorch with CUDA (never reinstall torch).
if ofb_conda_activate; then ok "conda env $OFB_CONDA_ENV"; else ofb_summary; exit 1; fi
if curl -sf -m 2 "$OFB_WORKER_URL/health" >/dev/null 2>&1; then
  fail "a worker already answers on $OFB_WORKER_URL" "stop it first (Ctrl+C in its pane, or ./robot/stop_all.sh)"
  ofb_summary; exit 1
fi
info "python $(command -v python) ($(python --version 2>&1))"
info "config $CONFIG (camera_mode $MODE)"
echo "== python scripts/vision_worker.py ${ARGS[*]}"
echo "   first start loads CLIP and may build a TensorRT engine: allow 1-5 minutes"
# NanoOWL loads its text model from huggingface.co; the lab Wi-Fi resets that
# connection (retries cost minutes). Use the cache once it exists.
if [ "$OFB_DETECTOR" = owl ] && [ -d "$HOME/.cache/huggingface/hub/models--google--owlvit-base-patch32" ]; then
  export HF_HUB_OFFLINE="${HF_HUB_OFFLINE:-1}"
fi
cd "$OFB_REPO" || exit 1
# The Jetson GPU cannot use page cache, and `free -m` hides that: on 2026-11-24 the
# NanoOWL worker answered 500 (TensorRT out of memory) with 2 GB "available". After
# this step it loaded 4 times out of 4. It takes about 30 s; OFB_DROP_CACHE=0 skips it.
case " ${ARGS[*]} " in *" --fake "*) FAKE_RUN=1 ;; *) FAKE_RUN=0 ;; esac   # a fake worker needs no GPU
if [ "${OFB_DROP_CACHE:-1}" != 0 ] && [ "$FAKE_RUN" != 1 ]; then
  info "dropping the page cache so the GPU can allocate (robot/lib/drop_cache.py)"
  python "$OFB_ROBOT_DIR/lib/drop_cache.py" || true
fi
exec python scripts/vision_worker.py "${ARGS[@]}"
