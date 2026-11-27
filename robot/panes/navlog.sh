#!/usr/bin/env bash
# Window "navigation" of the laptop launcher: what the robot decides and does, live.
# Shows the newest start_all log folder: the finder (query, candidates, result), the
# four-command navigator (plan, goal finished) and observations that saw something.
cd "$(dirname "$0")/../.." || exit 1
while true; do
  L="$(ls -td robot/logs/*_all 2>/dev/null | head -1)"
  if [ -z "$L" ]; then echo "no start_all log yet; waiting"; sleep 5; continue; fi
  echo "== $L  (Ctrl+C to close)"
  touch "$L/gridnav.log" "$L/objmem.log" 2>/dev/null
  tail -n 3 -F "$L/gridnav.log" "$L/objmem.log" 2>/dev/null \
    | grep --line-buffered -E "gridnav\]|objmem_finder\]|detections=[1-9]|memories=[1-9]|ERROR|WARN|FAIL" \
    | grep --line-buffered -v "observations=0 memories=0" \
    | sed -u -E 's/^\[objmem-[0-9]+\] //; s/\[[0-9]+\.[0-9]+\] //' &
  TAIL=$!
  # a newer start_all run: follow that one
  while [ "$(ls -td robot/logs/*_all 2>/dev/null | head -1)" = "$L" ]; do sleep 5; done
  kill $TAIL 2>/dev/null; pkill -P $$ tail 2>/dev/null
done
