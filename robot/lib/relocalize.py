#!/usr/bin/env python3
"""Find where the robot really is by matching the current LiDAR scan against the SLAM map.

Brute force over the whole map (0.1 m, 4 degrees), then a fine search around the best cell
(0.025 m, 1 degree). No initial guess is needed, so it also works after the robot was
carried somewhere or AMCL got lost. The robot must stand still.

  python3 robot/lib/relocalize.py robot/maps/room_l4.yaml            # print the pose
  python3 robot/lib/relocalize.py robot/maps/room_l4.yaml --compare "4.23 -3.54 -0.36"

Prints the best pose as the last line: "POSE x y yaw score" (meters, radians), or
"POSE none" when no place fits well enough (--min-score, default 0.55).
Score = share of beams that end on (or within a few cm of) a wall of the map; 1.0 = all.
Places that look alike are told apart by the beams that would pass through a wall there.
robot/relocalize.sh calls this and gives the pose to AMCL.

Use the full SLAM map, not the aisle copy (<name>_nav): in the aisle copy everything outside
the aisle is wall, so every pose fits. Python 3.8, numpy, PIL; needs ROS 2 for /scan.
"""
import argparse
import math
import os
import sys
import time

import numpy as np

LIDAR_X = -0.064      # base_scan in base_link (TurtleBot3 Waffle Pi): 6.4 cm behind the axle


def load_map(yaml_path):
    """(occupied[iy, ix] with iy growing with y, resolution, (origin_x, origin_y))."""
    from PIL import Image
    meta = {}
    with open(yaml_path) as f:
        for line in f:
            key, sep, value = line.partition(":")
            if sep:
                meta[key.strip()] = value.strip()
    image = meta["image"].strip("'" + '"')
    if not os.path.isabs(image):
        image = os.path.join(os.path.dirname(os.path.abspath(yaml_path)), image)
    with Image.open(image) as im:
        px = np.asarray(im.convert("L"))
    origin = [float(v) for v in meta["origin"].strip("[]").split(",")[:2]]
    return (px < 100)[::-1], float(meta["resolution"]), origin


def wall_field(occ, sigma_cells=2.0, reach=4):
    """1.0 on a wall cell, falling off over a few cells (a cheap likelihood field)."""
    f = occ.astype(np.float32)
    out = f.copy()
    for r in range(1, reach + 1):
        w = math.exp(-0.5 * (r / sigma_cells) ** 2)
        for dy, dx in ((r, 0), (-r, 0), (0, r), (0, -r), (r, r), (r, -r), (-r, r), (-r, -r)):
            sh = np.zeros_like(f)
            ys = slice(max(dy, 0), f.shape[0] + min(dy, 0)); yd = slice(max(-dy, 0), f.shape[0] + min(-dy, 0))
            xs = slice(max(dx, 0), f.shape[1] + min(dx, 0)); xd = slice(max(-dx, 0), f.shape[1] + min(-dx, 0))
            sh[ys, xs] = f[yd, xd]
            out = np.maximum(out, w * sh)
    return out


def scan_points(ranges, angle_min, angle_increment, r_min=0.15, r_max=6.0):
    """Beam end points in base_link (meters), bad and far returns dropped."""
    r = np.asarray(ranges, dtype=np.float64)
    a = angle_min + np.arange(len(r)) * angle_increment
    keep = np.isfinite(r) & (r > r_min) & (r < r_max)
    return np.stack([r[keep] * np.cos(a[keep]) + LIDAR_X, r[keep] * np.sin(a[keep])], 1)


def score(field, res, origin, pts, x, y, yaw):
    c, s = math.cos(yaw), math.sin(yaw)
    ix = ((x + c * pts[:, 0] - s * pts[:, 1] - origin[0]) / res).astype(int)
    iy = ((y + s * pts[:, 0] + c * pts[:, 1] - origin[1]) / res).astype(int)
    ok = (ix >= 0) & (ix < field.shape[1]) & (iy >= 0) & (iy < field.shape[0])
    return float(field[iy[ok], ix[ok]].sum()) / max(1, len(pts))


def crossing(occ, res, origin, pts, x, y, yaw, samples=12):
    """Share of beams that pass through a wall of the map before they end (0 = none).

    The end points alone cannot tell two similar places apart (two aisles between the same
    kind of desk rows); a pose in the wrong aisle makes many beams go through walls.
    """
    c, s = math.cos(yaw), math.sin(yaw)
    ox, oy = x + c * LIDAR_X, y + s * LIDAR_X
    ex = x + c * pts[:, 0] - s * pts[:, 1]
    ey = y + s * pts[:, 0] + c * pts[:, 1]
    length = np.hypot(ex - ox, ey - oy)
    # sample each beam between 0.15 m from the LiDAR and 0.25 m before its end
    hit = np.zeros(len(pts), bool)
    for t in np.linspace(0.0, 1.0, samples):
        d = 0.15 + t * np.maximum(0.0, length - 0.40)
        f = np.where(length > 1e-6, d / np.maximum(length, 1e-6), 0.0)
        ix = ((ox + f * (ex - ox) - origin[0]) / res).astype(int)
        iy = ((oy + f * (ey - oy) - origin[1]) / res).astype(int)
        ok = (ix >= 0) & (ix < occ.shape[1]) & (iy >= 0) & (iy < occ.shape[0]) & (length > 0.45)
        hit[ok] |= occ[iy[ok], ix[ok]]
    return float(hit.sum()) / max(1, len(pts))


def locate(field, res, origin, pts, step_cells=2, yaw_step_deg=4.0, beam_step=2, occ=None, keep=10):
    """Best (score, x, y, yaw) over the whole map. pts: scan points in base_link.

    Coarse search on the end points (score = share of beams ending on a wall), then the best
    `keep` places are refined (half a cell, 1 degree) and ranked by end-point score minus the
    share of beams that cross a wall (when occ, the wall map, is given).
    """
    h, w = field.shape
    xs = origin[0] + (np.arange(0, w, step_cells) + 0.5) * res
    ys = origin[1] + (np.arange(0, h, step_cells) + 0.5) * res
    sub = pts[::beam_step]
    cands = []
    for yaw in np.radians(np.arange(0.0, 360.0, yaw_step_deg)):
        c, s = math.cos(yaw), math.sin(yaw)
        px = c * sub[:, 0] - s * sub[:, 1]
        py = s * sub[:, 0] + c * sub[:, 1]
        acc = np.zeros((len(ys), len(xs)), np.float32)
        for k in range(len(px)):
            ix = ((xs + px[k] - origin[0]) / res).astype(int)
            iy = ((ys + py[k] - origin[1]) / res).astype(int)
            okx = (ix >= 0) & (ix < w)
            oky = (iy >= 0) & (iy < h)
            acc[np.ix_(oky, okx)] += field[np.ix_(iy[oky], ix[okx])]
        flat = np.argsort(acc, axis=None)[-3:]             # the three best cells of this heading
        for j in flat:
            jy, jx = np.unravel_index(int(j), acc.shape)
            cands.append((float(acc[jy, jx]) / len(px), float(xs[jx]), float(ys[jy]), float(yaw)))
    cands.sort(reverse=True)
    picked = []                                            # the best places, each one once
    for cand in cands:
        if all(math.hypot(cand[1] - q[1], cand[2] - q[2]) > 0.3
               or abs((cand[3] - q[3] + math.pi) % (2 * math.pi) - math.pi) > math.radians(15) for q in picked):
            picked.append(cand)
        if len(picked) >= keep:
            break
    half = step_cells * res
    best = None
    for _sc, bx, by, byaw in picked:
        fine = (-1.0, bx, by, byaw)
        for yaw in byaw + np.radians(np.arange(-yaw_step_deg, yaw_step_deg + 0.5, 1.0)):
            for x in np.arange(bx - half, bx + half + 1e-9, res / 2.0):
                for y in np.arange(by - half, by + half + 1e-9, res / 2.0):
                    sc = score(field, res, origin, pts, x, y, yaw)
                    if sc > fine[0]:
                        fine = (sc, float(x), float(y), float(yaw))
        cross = crossing(occ, res, origin, pts, fine[1], fine[2], fine[3]) if occ is not None else 0.0
        rank = fine[0] - cross
        if best is None or rank > best[0]:
            best = (rank, fine, cross)
    _rank, fine, _cross = best
    yaw = (fine[3] + math.pi) % (2 * math.pi) - math.pi
    return fine[0], fine[1], fine[2], yaw


def read_scan(seconds=3.0, need=8):
    """Median of a few scans (the robot stands still): (ranges, angle_min, angle_increment)."""
    import rclpy
    from rclpy.qos import qos_profile_sensor_data
    from sensor_msgs.msg import LaserScan

    rclpy.init()
    node = rclpy.create_node("ofb_relocalize")
    scans = []
    node.create_subscription(LaserScan, "/scan", scans.append, qos_profile_sensor_data)
    t0 = time.time()
    while time.time() - t0 < seconds + 6.0 and len(scans) < need:
        rclpy.spin_once(node, timeout_sec=0.2)
    node.destroy_node()
    rclpy.shutdown()
    if not scans:
        return None
    n = min(len(s.ranges) for s in scans)
    arr = np.array([[v if (v == v and 0.05 < v < 50.0) else np.nan for v in s.ranges[:n]] for s in scans], dtype=np.float64)
    seen = np.sum(~np.isnan(arr), axis=0) >= max(1, len(scans) // 2)
    med = np.full(n, np.nan)
    if seen.any():
        med[seen] = np.nanmedian(arr[:, seen], axis=0)
    return med, scans[-1].angle_min, scans[-1].angle_increment


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("map_yaml", help="the full SLAM map, e.g. robot/maps/room_l4.yaml")
    ap.add_argument("--min-score", type=float, default=0.55)
    ap.add_argument("--compare", default=None, help='"x y yaw": also print the score of this pose (e.g. AMCL\'s)')
    args = ap.parse_args(argv)

    occ, res, origin = load_map(args.map_yaml)
    field = wall_field(occ)
    got = read_scan()
    if got is None:
        print("[FAIL] no /scan: is bringup.sh running?")
        print("POSE none")
        return 1
    pts = scan_points(*got)
    if len(pts) < 40:
        print("[FAIL] only {} usable beams".format(len(pts)))
        print("POSE none")
        return 1
    t0 = time.time()
    sc, x, y, yaw = locate(field, res, origin, pts, occ=occ)
    print("scan: {} beams; searched the map in {:.0f} s".format(len(pts), time.time() - t0))
    if args.compare:
        cx, cy, cyaw = [float(v) for v in args.compare.split()[:3]]
        print("given pose  x {:.2f} y {:.2f} yaw {:.0f} deg: score {:.2f}, beams through walls {:.0f} %".format(
            cx, cy, math.degrees(cyaw), score(field, res, origin, pts, cx, cy, cyaw),
            100 * crossing(occ, res, origin, pts, cx, cy, cyaw)))
    print("best match  x {:.2f} y {:.2f} yaw {:.0f} deg: score {:.2f}, beams through walls {:.0f} %".format(
        x, y, math.degrees(yaw), sc, 100 * crossing(occ, res, origin, pts, x, y, yaw)))
    if sc < args.min_score:
        print("[FAIL] no place on the map fits the scan well (score {:.2f} < {:.2f})".format(sc, args.min_score))
        print("POSE none")
        return 1
    print("POSE {:.3f} {:.3f} {:.3f} {:.2f}".format(x, y, yaw, sc))
    return 0


if __name__ == "__main__":
    sys.exit(main())
