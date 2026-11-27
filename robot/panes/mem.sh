#!/usr/bin/env bash
# Window "memory": used / total RAM of the Jetson, every 2 s. The GPU shares this RAM.
# "free for apps" is what matters: below about 1000 MB a restart of the worker may fail.
while true; do
  awk -v now="$(date +%H:%M:%S)" '/MemTotal/{t=$2} /MemAvailable/{a=$2} /^MemFree/{f=$2} /^Cached/{c=$2} END{
    printf "%s  used %5d / total %5d MB   free for apps %5d MB   (really free %5d, cache %5d)
", now, (t-a)/1024, t/1024, a/1024, f/1024, c/1024}' /proc/meminfo
  sleep 2
done
