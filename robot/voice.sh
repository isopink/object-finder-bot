#!/usr/bin/env bash
# Spoken queries: microphone -> Whisper (conda env) -> /query.
# Start it after start_all.sh, in its own tmux window (Ctrl+B c). Ctrl+C or q stops it.
#
# Usage: ./robot/voice.sh [depth|nodepth] [scripts/voice_query.py args]
#   ./robot/voice.sh                      Enter = speak one query
#   ./robot/voice.sh --dry-run            only print what Whisper heard
#   ./robot/voice.sh --mic plughw:2,0     microphone from `arecord -l`
#
# Microphone: any USB microphone, or the C920's built-in microphone (the C920
# can stay plugged in for that even when the RealSense is the camera).
# Whisper (once, in the conda env; never let pip touch torch):
#   conda activate test1001
#   pip install --dry-run --no-deps openai-whisper     # check first
#   pip install --no-deps openai-whisper
#   pip install --dry-run tiktoken more-itertools numba tqdm   # must not change numpy/torch
#   pip install tiktoken more-itertools numba tqdm
# Optional, faster on the Jetson (TensorRT; uses the torch2trt already in the env):
#   pip install --dry-run --no-deps git+https://github.com/NVIDIA-AI-IOT/whisper_trt
#   pip install --no-deps git+https://github.com/NVIDIA-AI-IOT/whisper_trt
#   ./robot/voice.sh --trt        (falls back to openai-whisper if whisper_trt is missing)
set -uo pipefail
source "$(dirname "$0")/env.sh"
ofb_need_ros "$0" "$@"
ofb_log_init "voice"

MODE=depth
case "${1:-}" in depth|nodepth) MODE="$1"; shift ;; esac
CONFIG="$(ofb_make_config "$MODE")"

echo "== Microphone (arecord -l)"
if ! command -v arecord >/dev/null 2>&1; then
  fail "arecord not found" "sudo apt install alsa-utils"
  ofb_summary; exit 1
fi
arecord -l 2>/dev/null | sed 's/^/         /'
if arecord -l 2>/dev/null | grep 'card' >/dev/null; then ok "a capture device exists"; else
  fail "no capture device" "plug in a USB microphone (or the C920); then arecord -l"
  ofb_summary; exit 1
fi

if ofb_conda_activate; then ok "conda env $OFB_CONDA_ENV"; else ofb_summary; exit 1; fi
if python -c "import whisper" 2>/dev/null; then ok "import whisper"; else
  fail "import whisper" "install Whisper as in the header of robot/voice.sh (pip --no-deps)"
  ofb_summary; exit 1
fi

cd "$OFB_REPO" || exit 1
echo "== python scripts/voice_query.py --config $CONFIG $*"
exec python scripts/voice_query.py --config "$CONFIG" "$@"
