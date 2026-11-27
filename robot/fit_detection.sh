#!/usr/bin/env bash
# Measure how often the detector finds a present object at each distance, from the evidence
# log of a run (robot/logs/<run>/evidence.jsonl, written by objmem.sh), and optionally put the
# table into the config so that the next run counts a look by its distance.
#
# Before: put the objects down, let the robot remember them, then drive towards and away from
# them a few times (from 4 m to 0.6 m). Do NOT move the objects during that run.
#
# Usage: ./robot/fit_detection.sh [depth|nodepth] [--apply] [label ...]
#   ./robot/fit_detection.sh                 table and replay for the newest run, label "cup"
#   ./robot/fit_detection.sh cup laptop      count the memories with these labels
#   ./robot/fit_detection.sh --apply cup     also write d_by_range into robot/config/depth.yaml
#   OFB_EVIDENCE="a.jsonl b.jsonl"           use these logs instead of the newest one
#   OFB_MIN_LOOKS=30                         looks a distance bin needs to count
# Undo --apply: set "d_by_range: []" in the config (or git checkout robot/config/depth.yaml).
set -uo pipefail
source "$(dirname "$0")/env.sh"

MODE=depth; APPLY=0; LABELS=()
for a in "$@"; do
  case "$a" in
    depth|nodepth) MODE="$a" ;;
    --apply) APPLY=1 ;;
    -h|--help) sed -n '2,16p' "$0"; exit 0 ;;
    *) LABELS+=("$a") ;;
  esac
done
[ "${#LABELS[@]}" -eq 0 ] && LABELS=(cup)
CONFIG="$OFB_ROBOT_DIR/config/$MODE.yaml"

if [ -n "${OFB_EVIDENCE:-}" ]; then
  read -r -a LOGS <<< "$OFB_EVIDENCE"
else
  NEWEST="$(ls -t "$OFB_ROBOT_DIR"/logs/*/evidence.jsonl 2>/dev/null | head -1)"
  if [ -z "$NEWEST" ]; then
    fail "no robot/logs/*/evidence.jsonl" "run ./robot/start_all.sh <map> $MODE first; the log starts with the first remembered object"
    ofb_summary; exit 1
  fi
  LOGS=("$NEWEST")
fi
info "evidence log: ${LOGS[*]} ($(cat "${LOGS[@]}" 2>/dev/null | wc -l) frames)"
info "labels: ${LABELS[*]}   config: $CONFIG"

ARGS=("${LOGS[@]}" --config "$CONFIG" --compare --min-looks "${OFB_MIN_LOOKS:-30}")
for l in "${LABELS[@]}"; do ARGS+=(--label "$l"); done
[ "$APPLY" = 1 ] && ARGS+=(--write-config "$CONFIG")
/usr/bin/python3 "$OFB_REPO/scripts/fit_detection_range.py" "${ARGS[@]}"
RC=$?
if [ "$RC" = 0 ] && [ "$APPLY" = 1 ]; then
  ok "d_by_range written to $CONFIG (used from the next ./robot/start_all.sh)"
elif [ "$RC" = 0 ]; then
  ok "table printed; add --apply to write it into $CONFIG"
elif [ "$RC" = 2 ]; then
  fail "the table was not written" "drive past the objects more (each distance bin needs ${OFB_MIN_LOOKS:-30} looks) and keep them in place"
else
  fail "fit_detection_range.py failed (exit $RC)" "is python3-numpy / python3-yaml installed for /usr/bin/python3?"
fi
ofb_summary
