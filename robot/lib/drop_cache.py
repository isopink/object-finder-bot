#!/usr/bin/env python3
"""Drop clean page-cache pages of big files without root (posix_fadvise DONTNEED).

Why: on the Jetson the GPU allocator (NvMap) cannot use page cache. After an hour
of file reads MemFree was 3 GB and Cached 2 GB (2026-11-24); loading CLIP + the
NanoOWL TensorRT engine then used up the free memory and TensorRT failed with
"Cuda Runtime (out of memory)" (execution context None, every /detect_embed
answered 500) although `free -m` still showed 2 GB "available". A fresh boot does
not have the problem; `sudo sh -c 'echo 3 > /proc/sys/vm/drop_caches'` fixes it.
This script does the same without sudo: it asks the kernel to forget the cached
pages of every readable file of 256 KB or more under the usual model/library
folders. It only drops clean pages; nothing is deleted or changed.

robot/worker.sh runs it before the vision worker starts. Usage:
  python3 robot/lib/drop_cache.py            # prints MemFree / Cached before and after
Python 3.8, standard library only.
"""
import os
import sys

MIN_BYTES = 256 * 1024
SKIP = ("/proc", "/sys", "/dev", "/run")


def meminfo():
    out = {}
    with open("/proc/meminfo") as f:
        for line in f:
            k, _, v = line.partition(":")
            out[k] = int(v.split()[0]) // 1024  # MB
    return out


def roots():
    home = os.path.expanduser("~")
    cands = [home, "/usr/lib", "/usr/local", "/usr/src", "/opt", "/var/lib", "/var/cache"]
    return [p for p in cands if os.path.isdir(p)]


def drop(path):
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        return False
    try:
        os.posix_fadvise(fd, 0, 0, os.POSIX_FADV_DONTNEED)
        return True
    except OSError:
        return False
    finally:
        os.close(fd)


def main():
    before = meminfo()
    try:
        os.sync()  # dirty pages cannot be dropped until written
    except OSError:
        pass
    n = 0
    for root in roots():
        for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
            if dirpath.startswith(SKIP):
                dirnames[:] = []
                continue
            for name in filenames:
                p = os.path.join(dirpath, name)
                try:
                    if os.path.islink(p) or os.path.getsize(p) < MIN_BYTES:
                        continue
                except OSError:
                    continue
                if drop(p):
                    n += 1
    after = meminfo()
    print("drop_cache: %d files; MemFree %d -> %d MB, Cached %d -> %d MB"
          % (n, before.get("MemFree", 0), after.get("MemFree", 0), before.get("Cached", 0), after.get("Cached", 0)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
