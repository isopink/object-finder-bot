#!/usr/bin/env bash
# Window "memory": used / total RAM of the Jetson, every 2 s. The GPU shares this RAM.
# "free for apps" is what matters: below about 1000 MB a restart of the worker may fail.
while true; do
  t=$(awk '/^MemTotal/{print int($2/1024)}' /proc/meminfo)
  a=$(awk '/^MemAvailable/{print int($2/1024)}' /proc/meminfo)
  f=$(awk '/^MemFree/{print int($2/1024)}' /proc/meminfo)
  c=$(awk '/^Cached/{print int($2/1024)}' /proc/meminfo)
  printf "%s  used %5d / total %5d MB   free for apps %5d MB   (really free %5d, cache %5d)\n" \
    "$(date +%H:%M:%S)" "$((t - a))" "$t" "$a" "$f" "$c"
  sleep 2
done
