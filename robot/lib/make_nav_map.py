#!/usr/bin/env python3
"""Make a Nav2 copy of a SLAM map where desk rows become walls.

The LiDAR scans below the desk tops, so a SLAM map shows only the desk and chair
legs as dots and the space under the desks as free. The robot cannot go there (the
camera mast hits the desk top). This joins nearby obstacle dots (morphological
closing with --close m), then keeps only the free space connected to the start
point (map origin, or --start x y); every other free cell becomes occupied so Nav2
plans only through the aisles. The SLAM map itself is not changed.

  python3 robot/lib/make_nav_map.py robot/maps/room_l3.yaml --close 0.45
      -> robot/maps/room_l3_nav.yaml / .pgm   (use with nav.sh room_l3_nav)
  python3 robot/lib/make_nav_map.py robot/maps/room_l3.yaml --compare 0.3 0.45 0.6
      -> robot/maps/room_l3_nav_compare.png   (pick a value by eye)

Python 3.8, numpy, scipy, PIL (system Python on the Jetson). Written 2026-11-27.
"""
import argparse
import os
import sys

import numpy as np
from PIL import Image
from scipy import ndimage


def read_map(yaml_path):
    meta = {}
    with open(yaml_path) as f:
        for line in f:
            if ":" in line:
                k, v = line.split(":", 1)
                meta[k.strip()] = v.strip()
    img = os.path.join(os.path.dirname(os.path.abspath(yaml_path)), os.path.basename(meta["image"]))
    pix = np.array(Image.open(img).convert("L"))
    res = float(meta["resolution"])
    origin = [float(x) for x in meta["origin"].strip("[]").split(",")[:2]]
    return meta, img, pix, res, origin


def disk(r_cells):
    r = max(1, int(round(r_cells)))
    y, x = np.ogrid[-r:r + 1, -r:r + 1]
    return x * x + y * y <= r * r


def nav_grid(pix, res, origin, close_m, start_xy):
    occ = pix < 100
    free = pix > 250
    closed = ndimage.binary_closing(occ, structure=disk(close_m / res), iterations=1)
    walkable = free & ~closed
    h = pix.shape[0]
    sx = int(round((start_xy[0] - origin[0]) / res))
    sy = h - 1 - int(round((start_xy[1] - origin[1]) / res))
    labels, _ = ndimage.label(walkable)
    if not (0 <= sy < h and 0 <= sx < pix.shape[1]) or labels[sy, sx] == 0:
        # start cell is not walkable: take the largest walkable region instead
        sizes = np.bincount(labels.ravel())
        sizes[0] = 0
        keep = labels == int(np.argmax(sizes))
    else:
        keep = labels == labels[sy, sx]
    # Everything outside the aisle is occupied, unknown included: with Cartographer's
    # free_thresh 0.25 map_server reads gray (205) as FREE, and on 2026-11-27 Nav2
    # tried to drive around the outside of the scanned area.
    out = np.zeros(pix.shape, np.uint8)
    out[keep] = 254                                  # reachable aisle: free
    return out, (sx, sy)


def path_grid(pix, res, origin, path_xy, radius_m):
    """Free only within radius_m of where the robot drove (path in map x y)."""
    h, w = pix.shape
    on_path = np.zeros(pix.shape, bool)
    for x, y in path_xy:
        c = int(round((x - origin[0]) / res))
        r = h - 1 - int(round((y - origin[1]) / res))
        if 0 <= r < h and 0 <= c < w:
            on_path[r, c] = True
    dist = ndimage.distance_transform_edt(~on_path) * res
    free = pix > 250
    out = np.zeros(pix.shape, np.uint8)              # everything else occupied (see nav_grid)
    out[free & (dist <= radius_m)] = 254
    return out


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("yaml")
    ap.add_argument("--close", type=float, default=0.45, help="join obstacle dots closer than 2x this (m)")
    ap.add_argument("--start", type=float, nargs=2, default=[0.0, 0.0], help="a point in the aisle (map x y)")
    ap.add_argument("--compare", type=float, nargs="+", default=None, help="only write a side-by-side PNG")
    ap.add_argument("--path", default=None,
                    help="JSON list of [x, y] the robot drove (e.g. Cartographer's /trajectory_node_list);"
                         " then free = SLAM free within --radius of the path, and --close is ignored")
    ap.add_argument("--radius", type=float, nargs="+", default=[0.5], help="with --path: corridor half width (m)")
    args = ap.parse_args(argv)
    meta, img, pix, res, origin = read_map(args.yaml)
    base = os.path.splitext(os.path.abspath(args.yaml))[0]

    if args.path:
        import json
        with open(args.path) as f:
            path_xy = [tuple(p) for p in json.load(f)]
        if len(args.radius) > 1:
            pad = np.full((pix.shape[0], 6, 3), 255, np.uint8)
            tiles = [np.stack([pix] * 3, -1)] + [np.stack([path_grid(pix, res, origin, path_xy, r)] * 3, -1)
                                                 for r in args.radius]
            row = np.concatenate(sum([[t, pad] for t in tiles], [])[:-1], axis=1)
            out = base + "_nav_compare.png"
            Image.fromarray(row).resize((row.shape[1] * 3, row.shape[0] * 3), Image.NEAREST).save(out)
            print("wrote %s  (left: SLAM map, then radius = %s m)" % (out, ", ".join(str(r) for r in args.radius)))
            return 0
        g = path_grid(pix, res, origin, path_xy, args.radius[0])
        args.close = -1.0
    else:
        g = None

    if args.compare:
        tiles = [np.stack([pix] * 3, -1)]
        for c in args.compare:
            g, (sx, sy) = nav_grid(pix, res, origin, c, args.start)
            t = np.stack([g] * 3, -1)
            t[max(0, sy - 2):sy + 3, max(0, sx - 2):sx + 3] = (0, 170, 0)
            tiles.append(t)
        pad = np.full((pix.shape[0], 6, 3), 255, np.uint8)
        row = np.concatenate(sum([[t, pad] for t in tiles], [])[:-1], axis=1)
        out = base + "_nav_compare.png"
        Image.fromarray(row).resize((row.shape[1] * 3, row.shape[0] * 3), Image.NEAREST).save(out)
        print("wrote %s  (left: SLAM map, then close = %s m)" % (out, ", ".join(str(c) for c in args.compare)))
        return 0

    if g is None:
        g, _ = nav_grid(pix, res, origin, args.close, args.start)
    pgm = base + "_nav.pgm"
    Image.fromarray(g).save(pgm)
    with open(base + "_nav.yaml", "w") as f:
        f.write("image: %s\n" % os.path.basename(pgm))
        for k in ("mode", "resolution", "origin", "negate"):
            if k in meta:
                f.write("%s: %s\n" % (k, meta[k]))
        # ROS defaults: gray 205 stays unknown (Cartographer writes free_thresh 0.25).
        f.write("occupied_thresh: 0.65\nfree_thresh: 0.196\n")
    free_m2 = float((g == 254).sum()) * res * res
    print("wrote %s and .yaml: close %.2f m (-1 = path mode), aisle %.1f m^2 (SLAM map free %.1f m^2)"
          % (pgm, args.close, free_m2, float((pix > 250).sum()) * res * res))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
