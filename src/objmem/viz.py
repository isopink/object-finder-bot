"""Draw the object memory on a map as a PNG (PIL only, no matplotlib).

    png = draw_map(memory.items, robot_pose=pose, occupancy="maps/lab.yaml")
    open("map.png", "wb").write(png)

- objects: a dot with its 2-sigma covariance ellipse, colored by the existence
  confidence p (red = low, yellow = 0.5, green = high), labeled "label #id p=0.83";
- robot pose: a blue triangle; path: a blue line;
- occupancy: a map_saver map (path to the .yaml next to its .pgm), an
  ``OccupancyGrid``, or None (plain grid with 1 m lines);
- truth (optional): ground-truth positions drawn as black crosses.

PIL is imported inside the functions, so ``import objmem.viz`` works without it.
"""
import math
import os
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple, Union

import numpy as np

from objmem.types import MemoryItem, Pose2D


@dataclass
class OccupancyGrid:
    """Occupancy grid in ROS order: row 0 is the lowest y.

    grid values: -1 unknown, 0 free, 100 occupied (anything in between is shaded).
    origin: map coordinates (x, y) of the lower-left corner of cell (0, 0).
    """
    grid: np.ndarray
    resolution: float
    origin: Tuple[float, float]

    @property
    def extent(self) -> Tuple[float, float, float, float]:
        h, w = self.grid.shape[:2]
        x0, y0 = float(self.origin[0]), float(self.origin[1])
        return x0, y0, x0 + w * self.resolution, y0 + h * self.resolution


_MAP_CACHE = {}  # type: Dict[str, Tuple[float, OccupancyGrid]]


def load_map(yaml_path: str) -> OccupancyGrid:
    """Read a map written by nav2 map_saver (``<name>.yaml`` + its image).

    Cached by path and file modification time, so a map server can call this on
    every request.
    """
    import yaml
    from PIL import Image

    mtime = os.path.getmtime(yaml_path)
    hit = _MAP_CACHE.get(yaml_path)
    if hit is not None and hit[0] == mtime:
        return hit[1]
    with open(yaml_path, "r", encoding="utf-8") as fh:
        meta = yaml.safe_load(fh) or {}
    image = meta.get("image", os.path.splitext(yaml_path)[0] + ".pgm")
    if not os.path.isabs(image):
        image = os.path.join(os.path.dirname(os.path.abspath(yaml_path)), image)
    res = float(meta.get("resolution", 0.05))
    origin = meta.get("origin", [0.0, 0.0, 0.0])
    negate = int(meta.get("negate", 0))
    occ_t = float(meta.get("occupied_thresh", 0.65))
    free_t = float(meta.get("free_thresh", 0.25))
    pix = np.asarray(Image.open(image).convert("L"), dtype=float)
    occ = pix / 255.0 if negate else (255.0 - pix) / 255.0
    grid = np.full(pix.shape, -1, dtype=np.int8)
    grid[occ > occ_t] = 100
    grid[occ < free_t] = 0
    grid = grid[::-1].copy()  # image row 0 is the top (highest y)
    og = OccupancyGrid(grid=grid, resolution=res, origin=(float(origin[0]), float(origin[1])))
    _MAP_CACHE[yaml_path] = (mtime, og)
    return og


def p_color(p: float) -> Tuple[int, int, int]:
    """Red (p = 0) -> yellow (0.5) -> green (1)."""
    p = min(max(float(p), 0.0), 1.0)
    lo, mid, hi = (215, 48, 39), (240, 190, 40), (26, 150, 65)
    a, b, s = (lo, mid, p / 0.5) if p < 0.5 else (mid, hi, (p - 0.5) / 0.5)
    return tuple(int(round(a[i] + (b[i] - a[i]) * s)) for i in range(3))  # type: ignore


def _as_grid(occupancy) -> Optional[OccupancyGrid]:
    if occupancy is None:
        return None
    if isinstance(occupancy, OccupancyGrid):
        return occupancy
    if isinstance(occupancy, str):
        return load_map(occupancy)
    if isinstance(occupancy, (tuple, list)) and len(occupancy) == 3:
        grid, res, origin = occupancy
        return OccupancyGrid(np.asarray(grid), float(res), (float(origin[0]), float(origin[1])))
    raise TypeError("occupancy must be None, a map .yaml path, an OccupancyGrid, or (grid, resolution, origin)")


def _xy(p) -> Tuple[float, float]:
    if isinstance(p, Pose2D):
        return float(p.x), float(p.y)
    return float(p[0]), float(p[1])


def _known_extent(og: OccupancyGrid) -> Tuple[float, float, float, float]:
    known = np.argwhere(og.grid >= 0)
    if known.size == 0:
        return og.extent
    (r0, c0), (r1, c1) = known.min(axis=0), known.max(axis=0)
    x0, y0 = og.origin
    r = og.resolution
    return x0 + c0 * r, y0 + r0 * r, x0 + (c1 + 1) * r, y0 + (r1 + 1) * r


def _ellipse(mu: np.ndarray, cov: np.ndarray, nsig: float = 2.0, n: int = 40, cap: float = 6.0):
    cov = 0.5 * (np.asarray(cov, dtype=float) + np.asarray(cov, dtype=float).T)
    if not np.all(np.isfinite(cov)):
        return []
    vals, vecs = np.linalg.eigh(cov)
    axes = np.minimum(nsig * np.sqrt(np.maximum(vals, 0.0)), cap)
    ang = np.linspace(0.0, 2.0 * math.pi, n, endpoint=False)
    pts = vecs @ np.vstack([axes[0] * np.cos(ang), axes[1] * np.sin(ang)])
    return [(float(mu[0] + pts[0, i]), float(mu[1] + pts[1, i])) for i in range(n)]


def draw_map(items: Sequence[MemoryItem], robot_pose: Optional[Pose2D] = None,
             occupancy: Union[None, str, OccupancyGrid, tuple] = None,
             path: Optional[Sequence] = None, truth: Optional[Dict[str, Sequence[float]]] = None,
             title: Optional[str] = None, size: int = 800, highlight: Optional[int] = None,
             bounds: Optional[Tuple[float, float, float, float]] = None) -> bytes:
    """Render the memory as PNG bytes. See the module docstring.

    items: MemoryItems (mu, cov, p, id, label). path: Pose2D or (x, y) points.
    truth: name -> (x, y). highlight: an item id drawn with a thick outline.
    bounds: (x0, y0, x1, y1) in meters; default = the known map area, else
    everything drawn plus a 1 m margin. size: pixels of the longer side.
    """
    from PIL import Image, ImageDraw, ImageFont

    og = _as_grid(occupancy)
    items = list(items or [])
    path_xy = [_xy(p) for p in (path or [])]
    truth = dict(truth or {})

    if bounds is None:
        if og is not None:
            x0, y0, x1, y1 = _known_extent(og)
            m = 0.3
        else:
            pts = [(float(it.mu[0]), float(it.mu[1])) for it in items] + path_xy
            pts += [_xy(v) for v in truth.values() if v is not None and None not in tuple(v)[:2]]
            if robot_pose is not None:
                pts.append(_xy(robot_pose))
            pts = [p for p in pts if math.isfinite(p[0]) and math.isfinite(p[1])]
            if not pts:
                pts = [(0.0, 0.0)]
            xs, ys = [p[0] for p in pts], [p[1] for p in pts]
            x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
            m = 1.0
        x0, y0, x1, y1 = x0 - m, y0 - m, x1 + m, y1 + m
    else:
        x0, y0, x1, y1 = [float(v) for v in bounds]
    span = max(x1 - x0, y1 - y0, 2.0)
    s = (size - 40) / span  # pixels per meter
    left, top, bottom_pad = 20, 28, 36
    width = int(math.ceil((x1 - x0) * s)) + 2 * left
    height = int(math.ceil((y1 - y0) * s)) + top + bottom_pad

    def px(x: float, y: float) -> Tuple[float, float]:
        return left + (x - x0) * s, top + (y1 - y) * s

    img = Image.new("RGB", (width, height), (250, 250, 250))
    draw = ImageDraw.Draw(img)
    font = ImageFont.load_default()

    def label(xy, text, fill=(20, 20, 20)):
        try:
            box = draw.textbbox(xy, text, font=font)
        except AttributeError:  # Pillow < 8
            w, h = draw.textsize(text, font=font)
            box = (xy[0], xy[1], xy[0] + w, xy[1] + h)
        draw.rectangle([box[0] - 1, box[1] - 1, box[2] + 1, box[3] + 1], fill=(255, 255, 255))
        draw.text(xy, text, fill=fill, font=font)

    # occupancy grid
    if og is not None:
        g = og.grid.astype(int)
        rgb = np.full(g.shape + (3,), 205, dtype=np.uint8)
        free = g == 0
        occ = g >= 65
        mid = (g > 0) & (g < 65)
        rgb[free] = (245, 245, 245)
        rgb[occ] = (90, 90, 90)
        rgb[mid] = (150, 150, 150)
        rgb = rgb[::-1]  # top row = highest y
        ox0, oy0, ox1, oy1 = og.extent
        tile = Image.fromarray(rgb, "RGB").resize(
            (max(1, int(round((ox1 - ox0) * s))), max(1, int(round((oy1 - oy0) * s)))), Image.NEAREST)
        tx, ty = px(ox0, oy1)
        img.paste(tile, (int(round(tx)), int(round(ty))))
        draw = ImageDraw.Draw(img)
    # 1 m grid lines
    for gx in range(int(math.ceil(x0)), int(math.floor(x1)) + 1):
        a, b = px(gx, y0), px(gx, y1)
        draw.line([a, b], fill=(225, 225, 235) if og is None else (180, 180, 200), width=1)
        draw.text((a[0] + 2, a[1] - 12), str(gx), fill=(120, 120, 140), font=font)
    for gy in range(int(math.ceil(y0)), int(math.floor(y1)) + 1):
        a, b = px(x0, gy), px(x1, gy)
        draw.line([a, b], fill=(225, 225, 235) if og is None else (180, 180, 200), width=1)
        draw.text((a[0] + 2, a[1] - 12), str(gy), fill=(120, 120, 140), font=font)

    # path
    if len(path_xy) >= 2:
        draw.line([px(*p) for p in path_xy], fill=(120, 160, 230), width=2)

    # ground truth
    for name, xy in sorted(truth.items()):
        if xy is None or xy[0] is None or xy[1] is None:
            continue
        cx, cy = px(float(xy[0]), float(xy[1]))
        r = 5
        draw.line([(cx - r, cy - r), (cx + r, cy + r)], fill=(190, 0, 170), width=2)
        draw.line([(cx - r, cy + r), (cx + r, cy - r)], fill=(190, 0, 170), width=2)
        label((cx + 6, cy + 3), str(name), fill=(150, 0, 130))

    # memories, lowest p first so confident ones are on top
    for it in sorted(items, key=lambda i: float(i.p)):
        mu = np.asarray(it.mu, dtype=float)
        if not np.all(np.isfinite(mu)):
            continue
        col = p_color(it.p)
        ring = _ellipse(mu, it.cov)
        if len(ring) >= 3:
            w = 3 if highlight is not None and it.id == highlight else 1
            pts = [px(*q) for q in ring]
            draw.line(pts + [pts[0]], fill=col, width=w)
        cx, cy = px(mu[0], mu[1])
        r = 6 if highlight is not None and it.id == highlight else 4
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=col, outline=(30, 30, 30))
        text = "{} #{} p={:.2f}".format(it.label, it.id, it.p) if it.label else "#{} p={:.2f}".format(it.id, it.p)
        label((cx + 6, cy - 13), text)

    # robot
    if robot_pose is not None:
        rx, ry, ryaw = float(robot_pose.x), float(robot_pose.y), float(robot_pose.yaw)
        L = 0.25
        tri = [(rx + L * math.cos(ryaw), ry + L * math.sin(ryaw)),
               (rx + 0.6 * L * math.cos(ryaw + 2.5), ry + 0.6 * L * math.sin(ryaw + 2.5)),
               (rx + 0.6 * L * math.cos(ryaw - 2.5), ry + 0.6 * L * math.sin(ryaw - 2.5))]
        draw.polygon([px(*q) for q in tri], fill=(40, 90, 220), outline=(10, 30, 120))

    # title and p legend
    draw.text((left, 8), title or "object memory: {} items".format(len(items)), fill=(20, 20, 20), font=font)
    lx, ly = left, height - 22
    draw.text((lx, ly), "p", fill=(20, 20, 20), font=font)
    for i in range(100):
        draw.line([(lx + 12 + i, ly), (lx + 12 + i, ly + 10)], fill=p_color(i / 99.0))
    draw.text((lx + 116, ly), "0 .. 1     x (magenta) = ground truth     ellipse = 2 sigma", fill=(80, 80, 80), font=font)

    import io
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def save_map(filename: str, items: Sequence[MemoryItem], **kw) -> str:
    """draw_map(items, **kw) written to a PNG file. Returns the file name."""
    folder = os.path.dirname(os.path.abspath(filename))
    if not os.path.isdir(folder):
        os.makedirs(folder)
    with open(filename, "wb") as fh:
        fh.write(draw_map(items, **kw))
    return filename


__all__ = ["OccupancyGrid", "load_map", "draw_map", "save_map", "p_color"]
