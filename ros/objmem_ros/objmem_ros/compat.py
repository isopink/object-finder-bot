"""Access to the objmem modules other sessions write, with small stand-ins.

Each getter returns the real objmem implementation when it can be imported and
a minimal stand-in that follows the shared brief otherwise. The stand-ins exist
only so this package can be built and tested before the lanes are merged; the
integrator removes them once every real module is on main.

No rclpy here. Standard library + numpy only.
"""
import base64
import json
import math
import urllib.request
from typing import List

import numpy as np

from objmem.types import (Candidate, Detection, MemoryItem, Observation, Params, Pose2D,
                          SearchResult)

# Names of the stand-ins in use, for the startup log.
FALLBACKS = []  # type: List[str]


def _note(name):
    if name not in FALLBACKS:
        FALLBACKS.append(name)


# ---------------------------------------------------------------- memory
def memory_class():
    """objmem.memory.ObjectMemory, or the stand-in."""
    try:
        from objmem.memory import ObjectMemory
        return ObjectMemory
    except ImportError:
        _note("memory")
        return FallbackMemory


def _normalize(v):
    v = np.asarray(v, dtype=np.float32)
    n = float(np.linalg.norm(v))
    return v / n if n > 0 else v


class FallbackMemory(object):
    """Minimal MemoryAPI: Kalman position fusion, Bayes confidence, no decay subtleties."""

    def __init__(self, params):
        self.params = params
        self._items = []  # type: List[MemoryItem]
        self._next_id = 0

    @property
    def items(self):
        return list(self._items)

    def _pos(self, p):
        d, f = self.params.d, self.params.f
        return d * p / (d * p + f * (1.0 - p))

    def _neg(self, p):
        d, f = self.params.d, self.params.f
        return (1.0 - d) * p / ((1.0 - d) * p + (1.0 - f) * (1.0 - p))

    def update_frame(self, observations, pose, in_view, t):
        used = set()
        for obs in observations:
            best, best_d = None, None
            for it in self._items:
                if it.id in used:
                    continue
                diff = obs.mu - it.mu
                s = it.cov + obs.cov
                maha = float(math.sqrt(max(diff @ np.linalg.solve(s, diff), 0.0)))
                cos = float(np.dot(_normalize(obs.embedding), it.embedding))
                if maha <= self.params.maha_thresh and cos >= self.params.cos_thresh:
                    if best_d is None or maha < best_d:
                        best, best_d = it, maha
            if best is None:
                self._items.append(MemoryItem(
                    id=self._next_id, mu=np.array(obs.mu, dtype=float), cov=np.array(obs.cov, dtype=float),
                    embedding=_normalize(obs.embedding), p=self.params.p_init, t_last=t, n_obs=1,
                    view_pose=obs.view_pose, label=obs.label))
                used.add(self._next_id)
                self._next_id += 1
                continue
            k = best.cov @ np.linalg.inv(best.cov + obs.cov)
            best.mu = best.mu + k @ (obs.mu - best.mu)
            best.cov = (np.eye(2) - k) @ best.cov
            best.embedding = _normalize(best.embedding * best.n_obs + _normalize(obs.embedding))
            best.n_obs += 1
            best.p = self._pos(best.p)
            best.t_last = t
            best.view_pose = obs.view_pose
            used.add(best.id)
        for it in self._items:
            if it.id not in used and in_view(it.mu, pose):
                it.p = self._neg(it.p)

    def query(self, text_embedding, t, k=None):
        if not self._items:
            return []
        k = self.params.top_k if k is None else k
        q = _normalize(text_embedding)
        sims = np.array([float(np.dot(q, it.embedding)) for it in self._items])
        z = np.exp((sims - sims.max()) / self.params.T)
        soft = z / z.sum()
        cands = [Candidate(item=it, sim=float(s), score=float(w * it.p))
                 for it, s, w in zip(self._items, sims, soft)]
        cands.sort(key=lambda c: -c.score)
        return cands[:k]

    def _get(self, item_id):
        for it in self._items:
            if it.id == item_id:
                return it
        raise KeyError(item_id)

    def mark_found(self, item_id, t):
        it = self._get(item_id)
        it.p = self._pos(it.p)
        it.t_last = t

    def mark_not_found(self, item_id, t):
        it = self._get(item_id)
        it.p = self._neg(it.p)

    def save(self, path):
        its = self._items
        np.savez(
            path,
            id=np.array([i.id for i in its], dtype=np.int64),
            mu=np.array([i.mu for i in its], dtype=float).reshape(-1, 2),
            cov=np.array([i.cov for i in its], dtype=float).reshape(-1, 2, 2),
            embedding=np.array([i.embedding for i in its], dtype=np.float32).reshape(len(its), -1),
            p=np.array([i.p for i in its], dtype=float),
            t_last=np.array([i.t_last for i in its], dtype=float),
            n_obs=np.array([i.n_obs for i in its], dtype=np.int64),
            view_pose=np.array([[i.view_pose.x, i.view_pose.y, i.view_pose.yaw] for i in its],
                               dtype=float).reshape(-1, 3),
            label=np.array([i.label or "" for i in its], dtype=str),
            next_id=np.array(self._next_id),
        )

    @classmethod
    def load(cls, path, params):
        mem = cls(params)
        with np.load(path, allow_pickle=False) as z:
            for j in range(len(z["id"])):
                vp = z["view_pose"][j]
                mem._items.append(MemoryItem(
                    id=int(z["id"][j]), mu=np.array(z["mu"][j]), cov=np.array(z["cov"][j]),
                    embedding=np.array(z["embedding"][j]), p=float(z["p"][j]),
                    t_last=float(z["t_last"][j]), n_obs=int(z["n_obs"][j]),
                    view_pose=Pose2D(float(vp[0]), float(vp[1]), float(vp[2])),
                    label=str(z["label"][j]) or None))
            mem._next_id = int(z["next_id"])
        return mem


# ---------------------------------------------------------------- geometry
def observe_fn():
    """objmem.geometry.observe, or the stand-in."""
    try:
        from objmem.geometry import observe
        return observe
    except ImportError:
        _note("geometry.observe")
        return fallback_observe


def make_in_view_fn():
    """objmem.geometry.make_in_view, or the stand-in."""
    try:
        from objmem.geometry import make_in_view
        return make_in_view
    except ImportError:
        _note("geometry.make_in_view")
        return fallback_make_in_view


def median_depth_fn():
    try:
        from objmem.geometry import median_depth
        return median_depth
    except ImportError:
        _note("geometry.median_depth")
        return fallback_median_depth


def fallback_median_depth(depth, box, frac=0.3):
    l, t, r, b = [int(v) for v in box]
    cx, cy = (l + r) / 2.0, (t + b) / 2.0
    hw, hh = max(1.0, (r - l) * frac / 2.0), max(1.0, (b - t) * frac / 2.0)
    h, w = depth.shape[:2]
    x0, x1 = int(max(0, cx - hw)), int(min(w, cx + hw + 1))
    y0, y1 = int(max(0, cy - hh)), int(min(h, cy + hh + 1))
    patch = np.asarray(depth[y0:y1, x0:x1], dtype=float)
    valid = patch[patch > 0]
    if valid.size == 0:
        return None
    return float(np.median(valid))


def _rot(a):
    c, s = math.cos(a), math.sin(a)
    return np.array([[c, -s], [s, c]])


def fallback_observe(det, pose, params, t):
    """Flat-ground approximation of geometry.observe (camera pitch ignored)."""
    u = (det.box[0] + det.box[2]) / 2.0
    ang_cam = -math.atan2(u - params.cx, params.fx) + params.cam_yaw
    cam_xy = np.array([pose.x, pose.y]) + _rot(pose.yaw) @ np.array([params.cam_x, params.cam_y])
    bearing = pose.yaw + ang_cam
    ray = np.array([math.cos(bearing), math.sin(bearing)])
    if params.camera_mode == "depth":
        r = det.depth_m
        if r is None or r < params.depth_min or r > params.depth_max:
            return None
        s_r = params.sigma_range_a + params.sigma_range_b * r * r
        s_l = r * params.sigma_bearing
        b_out = None
    else:
        r = params.nominal_range
        s_r = params.sigma_range_nodepth
        s_l = r * params.sigma_bearing
        b_out = bearing
    rot = _rot(bearing)
    cov = rot @ np.diag([s_r ** 2, s_l ** 2]) @ rot.T
    return Observation(embedding=_normalize(det.embedding), mu=cam_xy + r * ray, cov=cov, t=t,
                       view_pose=pose, label=det.label, bearing=b_out)


def fallback_make_in_view(params):
    def in_view(mu, pose):
        d = np.asarray(mu, dtype=float) - np.array([pose.x, pose.y])
        r = float(np.linalg.norm(d))
        ang = math.atan2(d[1], d[0]) - pose.yaw - params.cam_yaw
        ang = math.atan2(math.sin(ang), math.cos(ang))
        lo = params.depth_min if params.camera_mode == "depth" else 0.0
        return abs(ang) <= params.hfov / 2.0 and lo <= r <= params.depth_max
    return in_view


# ---------------------------------------------------------------- search
def find_fn():
    """objmem.search.find, or the stand-in."""
    try:
        from objmem.search import find
        return find
    except ImportError:
        _note("search.find")
        return fallback_find


def goal_for_fn():
    try:
        from objmem.search import goal_for
        return goal_for
    except ImportError:
        _note("search.goal_for")
        return fallback_goal_for


def fallback_goal_for(item, params):
    if float(np.linalg.eigvalsh(item.cov).max()) > params.pos_cov_max:
        return item.view_pose
    vp = np.array([item.view_pose.x, item.view_pose.y])
    d = vp - item.mu
    n = float(np.linalg.norm(d))
    u = d / n if n > 1e-6 else np.array([-math.cos(item.view_pose.yaw), -math.sin(item.view_pose.yaw)])
    g = item.mu + params.standoff * u
    return Pose2D(float(g[0]), float(g[1]), math.atan2(-u[1], -u[0]))


def fallback_find(text, memory, embedder, navigator, verifier, params, clock=None):
    import time
    clock = clock or time.time
    cands = memory.query(embedder.embed_text(text), clock())
    if not cands:
        return SearchResult(status="empty", item=None, tried=[])
    tried = []
    for c in cands:
        if not navigator.go_to(fallback_goal_for(c.item, params)):
            if not navigator.go_to(c.item.view_pose):
                tried.append((c.item.id, "nav_failed"))
                continue
        found, _prob = verifier.check(text)
        if found:
            memory.mark_found(c.item.id, clock())
            tried.append((c.item.id, "found"))
            return SearchResult(status="found", item=c.item, tried=tried)
        memory.mark_not_found(c.item.id, clock())
        tried.append((c.item.id, "not_found"))
    status = "not_found" if any(o == "not_found" for _, o in tried) else "nav_failed"
    return SearchResult(status=status, item=None, tried=tried)


# ---------------------------------------------------------------- worker client
def _post(url, path, body, timeout):
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url.rstrip("/") + path, data=data,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def parse_detections(reply):
    out = []
    for d in reply.get("detections", []):
        out.append(Detection(box=tuple(int(v) for v in d["box"]), label=str(d.get("label", "")),
                             conf=float(d.get("conf", 0.0)),
                             embedding=_normalize(np.asarray(d["embedding"], dtype=np.float32)),
                             depth_m=None if d.get("depth_m") is None else float(d["depth_m"])))
    return out


def detect_embed_jpeg(url, jpeg, timeout=10.0):
    """POST /detect_embed. jpeg=None lets the worker read its own camera."""
    body = {} if jpeg is None else {"image_jpeg_b64": base64.b64encode(bytes(jpeg)).decode("ascii")}
    return parse_detections(_post(url, "/detect_embed", body, timeout))


class FallbackClient(object):
    """Subset of objmem.worker.VisionClient used by the nodes (no image encoding)."""

    def __init__(self, url, timeout=10.0):
        self.url, self.timeout = url, timeout

    def health(self):
        with urllib.request.urlopen(self.url.rstrip("/") + "/health", timeout=self.timeout) as r:
            return json.loads(r.read().decode("utf-8"))

    def detect_embed(self, color=None):
        if color is not None:
            raise NotImplementedError("stand-in client sends no images; use detect_embed_jpeg")
        return detect_embed_jpeg(self.url, None, self.timeout)

    def verify(self, text, color=None):
        if color is not None:
            raise NotImplementedError("stand-in client sends no images")
        r = _post(self.url, "/verify", {"text": text}, self.timeout)
        return bool(r["found"]), float(r["prob"])

    def embed_text(self, text):
        r = _post(self.url, "/embed_text", {"text": text}, self.timeout)
        return _normalize(np.asarray(r["embedding"], dtype=np.float32))


class FallbackVerifier(object):
    def __init__(self, client):
        self.client = client

    def check(self, text):
        return self.client.verify(text)


def vision_client(url, timeout=10.0):
    try:
        from objmem.worker import VisionClient
        return VisionClient(url, timeout=timeout)
    except ImportError:
        _note("worker.VisionClient")
        return FallbackClient(url, timeout)


def client_verifier(client):
    try:
        from objmem.worker import ClientVerifier
        return ClientVerifier(client)
    except ImportError:
        _note("worker.ClientVerifier")
        return FallbackVerifier(client)


class ClientTextEmbedder(object):
    """Embedder whose embed_text goes to the worker; search.find needs only embed_text."""

    def __init__(self, client):
        self.client = client

    def embed_text(self, text):
        return self.client.embed_text(text)

    def embed_images(self, images):
        raise NotImplementedError("image embedding happens in the vision worker")


# ---------------------------------------------------------------- drawing
def draw_map_fn():
    """objmem.viz.draw_map, or a dependency-free stand-in."""
    try:
        from objmem.viz import draw_map
        return draw_map
    except ImportError:
        _note("viz.draw_map")
        return fallback_draw_map


def _png(rgb):
    import struct
    import zlib
    h, w = rgb.shape[:2]
    raw = b"".join(b"\x00" + rgb[y].tobytes() for y in range(h))

    def chunk(tag, data):
        c = struct.pack(">I", len(data)) + tag + data
        return c + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def fallback_draw_map(items, robot_pose=None, occupancy=None, path=None):
    """Objects as squares colored by p (red low, green high), robot in blue. No labels."""
    size, margin = 400, 20
    img = np.full((size, size, 3), 255, dtype=np.uint8)
    pts = [it.mu for it in items] + ([np.array([robot_pose.x, robot_pose.y])] if robot_pose else [])
    if pts:
        arr = np.array(pts, dtype=float)
        lo, hi = arr.min(axis=0) - 0.5, arr.max(axis=0) + 0.5
    else:
        lo, hi = np.array([-1.0, -1.0]), np.array([1.0, 1.0])
    scale = (size - 2 * margin) / float(max(hi - lo))

    def px(xy):
        return (int(margin + (xy[0] - lo[0]) * scale), int(size - margin - (xy[1] - lo[1]) * scale))

    def dot(xy, color, r=4):
        x, y = px(xy)
        img[max(0, y - r):y + r + 1, max(0, x - r):x + r + 1] = color
    for it in items:
        dot(it.mu, (int(255 * (1 - it.p)), int(200 * it.p), 0))
    if robot_pose is not None:
        dot((robot_pose.x, robot_pose.y), (0, 0, 255), 6)
    return _png(img)


__all__ = ["FALLBACKS", "Params", "Pose2D"]


def probe_all():
    """Resolve every getter once so FALLBACKS lists all stand-ins in use. Returns FALLBACKS."""
    for getter in (memory_class, observe_fn, make_in_view_fn, median_depth_fn, find_fn, goal_for_fn,
                   draw_map_fn):
        getter()
    try:
        from objmem.worker import ClientVerifier, VisionClient  # noqa: F401
    except ImportError:
        _note("worker.VisionClient")
        _note("worker.ClientVerifier")
    return list(FALLBACKS)
