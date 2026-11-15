#!/usr/bin/env python3
"""Summarize a map saved by map_saver: size, resolution, origin, free/occupied/unknown.

Usage: python3 robot/lib/map_info.py robot/maps/<name>.yaml

Standard library only (reads the .yaml with a tiny parser and the binary .pgm
directly), so it runs with any python3. Exit status 1 if the map is missing,
unreadable, or almost empty. Python 3.8 syntax.
"""
import os
import sys


def read_yaml(path):
    """Read the flat keys map_saver writes (image, resolution, origin, thresholds)."""
    out = {}
    with open(path) as f:
        for line in f:
            line = line.split("#", 1)[0].strip()
            if ":" not in line:
                continue
            k, v = line.split(":", 1)
            out[k.strip()] = v.strip()
    return out


def read_pgm(path):
    """Return (width, height, maxval, bytes) of a binary P5 PGM."""
    with open(path, "rb") as f:
        data = f.read()
    tokens = []
    i = 0
    while len(tokens) < 4:
        while data[i:i + 1].isspace():
            i += 1
        if data[i:i + 1] == b"#":
            while data[i:i + 1] not in (b"\n", b""):
                i += 1
            continue
        j = i
        while not data[j:j + 1].isspace():
            j += 1
        tokens.append(data[i:j])
        i = j
    i += 1  # single whitespace after maxval
    if tokens[0] != b"P5":
        raise ValueError("not a binary PGM (P5): %r" % tokens[0])
    w, h, maxval = int(tokens[1]), int(tokens[2]), int(tokens[3])
    return w, h, maxval, data[i:i + w * h]


def main(argv):
    if len(argv) != 2:
        print(__doc__)
        return 2
    yaml_path = argv[1]
    meta = read_yaml(yaml_path)
    image = meta.get("image", "")
    pgm_path = image if os.path.isabs(image) else os.path.join(os.path.dirname(yaml_path), image)
    w, h, maxval, pix = read_pgm(pgm_path)
    res = float(meta.get("resolution", "0.05"))
    # map_saver trinary defaults: 254 free, 0 occupied, 205 unknown.
    free = sum(1 for p in pix if p >= 250)
    occ = sum(1 for p in pix if p <= 10)
    n = max(1, w * h)
    unknown = n - free - occ
    print("image      %s" % pgm_path)
    print("size       %d x %d cells = %.1f x %.1f m (resolution %.3f m)" % (w, h, w * res, h * res, res))
    print("origin     %s" % meta.get("origin", "?"))
    print("free       %5.1f %%  (%.1f m^2)" % (100.0 * free / n, free * res * res))
    print("occupied   %5.1f %%" % (100.0 * occ / n))
    print("unknown    %5.1f %%" % (100.0 * unknown / n))
    if free * res * res < 2.0:
        print("map looks almost empty (< 2 m^2 free): drive more before saving")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
