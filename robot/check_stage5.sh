#!/usr/bin/env bash
# Stage 5: the full loop. Run after ./robot/start_all.sh <map> [depth|nodepth]
# and after the robot has seen some objects (drive it around with teleop.sh or
# let it patrol). Sends one query and prints the status messages.
#
# Usage: ./robot/check_stage5.sh ["a blue mug"] [timeout_s]
set -uo pipefail
source "$(dirname "$0")/env.sh"
ofb_need_ros "$0" "$@"
ofb_log_init check_stage5

QUERY="${1:-a cup}"
QUERY="${QUERY//\'/}"
QUERY="${QUERY//\"/}"
TMO="${2:-240}"
SESSION="${OFB_TMUX_SESSION:-ofb}"

echo "== 1. Processes"
if command -v tmux >/dev/null 2>&1 && tmux has-session -t "$SESSION" 2>/dev/null; then ok "tmux session '$SESSION'"; else
  info "no tmux session '$SESSION' visible from here (normal inside Docker); checking the pieces directly"
fi
if H="$(curl -sf -m 3 "$OFB_WORKER_URL/health")"; then ok "vision worker: $H"; else
  fail "vision worker not answering on $OFB_WORKER_URL" "worker pane; or ./robot/check_stage4.sh <mode>"
fi
NODES="$(ros2 node list 2>/dev/null)"
for n in objmem_observer objmem_finder objmem_mapview; do
  if grep -q "$n" <<<"$NODES"; then ok "node $(grep "$n" <<<"$NODES" | head -n 1)"; else
    fail "no $n node" "objmem pane: ros2 launch objmem_ros objmem.launch.py ...; ./robot/build_ws.sh after git pull"
  fi
done
if ros2 action list 2>/dev/null | grep -x /navigate_to_pose >/dev/null; then ok "Nav2 /navigate_to_pose"; else
  fail "no /navigate_to_pose" "nav pane (./robot/nav.sh <map>)"
fi

echo "== 2. Topics and map view"
TOPICS="$(ros2 topic list 2>/dev/null)"
for t in /query /objmem/status /objmem/markers; do
  if grep -qx "$t" <<<"$TOPICS"; then ok "topic $t"; else fail "no topic $t" "objmem nodes not running"; fi
done
CODE="$(curl -s -o /dev/null -m 5 -w '%{http_code}' "http://127.0.0.1:$OFB_MAPVIEW_PORT/" || true)"
if [ "$CODE" = 200 ]; then ok "map view http://<jetson-ip>:$OFB_MAPVIEW_PORT/ answers"; else
  fail "map view on port $OFB_MAPVIEW_PORT returned '$CODE'" "mapview node running? port taken? (ss -ltnp | grep $OFB_MAPVIEW_PORT)"
fi
MEMS="$(ls -1 "$OFB_ROBOT_DIR"/memory/*.npz 2>/dev/null | head -n 3)"
if [ -n "$MEMS" ]; then ok "memory file(s): $(echo "$MEMS" | tr '\n' ' ')"; else
  info "no memory file yet in robot/memory/ (the observer saves periodically)"
fi

# ros2 topic echo prints YAML: data: 'result: found ...' (quoted when it has ": ").
strip_data() { sed -E "s/^data: ['\"]?//; s/['\"]\$//"; }

echo "== 3. One query: \"$QUERY\" (up to ${TMO}s)"
STATUS="$OFB_LOG_DIR/status.txt"
timeout "$TMO" ros2 topic echo /objmem/status > "$STATUS" 2>/dev/null &
ECHO=$!
sleep 3
T0=$(date +%s)
if timeout 15 ros2 topic pub --once /query std_msgs/msg/String "{data: '$QUERY'}" >/dev/null 2>&1; then
  ok "published /query"
else
  fail "could not publish /query"
fi
# The search drives to each candidate, so messages can be a minute apart.
# Stop after 60 s without a new message (once one arrived), or at the timeout.
LAST_N=0; LAST_T=$(date +%s)
while kill -0 "$ECHO" 2>/dev/null; do
  CUR_N="$(grep -c '^data:' "$STATUS" 2>/dev/null || true)"
  if [ "${CUR_N:-0}" != "$LAST_N" ]; then
    grep '^data:' "$STATUS" | tail -n +$((LAST_N + 1)) | strip_data | sed 's/^/  [..]   status: /'
    LAST_N="${CUR_N:-0}"; LAST_T=$(date +%s)
  fi
  # The finder ends every search with a "result:" line.
  if grep -Eq "^data: ['\"]?result" "$STATUS"; then sleep 1; break; fi
  if [ "$LAST_N" -gt 0 ] && [ $(( $(date +%s) - LAST_T )) -ge 60 ]; then
    break
  fi
  sleep 2
done
kill "$ECHO" 2>/dev/null; wait "$ECHO" 2>/dev/null
DT=$(( $(date +%s) - T0 ))
N="$(grep -c '^data:' "$STATUS" || true)"
echo "  ${N} status message(s) in ${DT}s (all saved in $STATUS)"
if grep -Eq "^data: ['\"]?(query|candidates|result)" "$STATUS"; then ok "finder answered the query"; else
  fail "no query/candidates/result status after the query" "finder node running? read the objmem pane / objmem.log"
fi
LAST="$(grep -E "^data: ['\"]?result" "$STATUS" | tail -n 1 | strip_data)"
if [ -z "$LAST" ]; then
  fail "no result: line within ${TMO}s" "the search may still be running (see the ask pane); raise the timeout: $0 \"$QUERY\" 600"
elif grep -Eiq "found" <<<"$LAST" && ! grep -Eiq "not[ _]found" <<<"$LAST"; then
  ok "$LAST"
else
  info "$LAST (empty memory? all candidates failed? see the status lines above)"
fi

ofb_summary
echo "Copy back (logs, memory, search log):"
echo "  scp -r <user>@<jetson-ip>:$OFB_LOG_DIR ./"
echo "  scp -r <user>@<jetson-ip>:$OFB_ROBOT_DIR/memory ./"
