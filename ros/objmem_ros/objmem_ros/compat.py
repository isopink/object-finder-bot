"""The objmem functions the ROS nodes use, in one place.

Everything here is the real objmem implementation (memory, geometry, search,
worker client, viz). The only fallback left is `plain_draw_map`, a PNG drawing
without PIL, used by mapview when python3-pil is missing or draw_map fails.

No rclpy here. Standard library + numpy only.
"""
import base64
import json
import urllib.request
from typing import List

import numpy as np

from objmem.geometry import make_in_view, median_depth, observe
from objmem.memory import ObjectMemory
from objmem.search import find, goal_for
from objmem.types import Detection, Params, Pose2D
from objmem.worker import ClientEmbedder, ClientVerifier, VisionClient

# Optional parts that are missing, for the startup log (only "PIL" can appear).
FALLBACKS = []  # type: List[str]

# search.find needs only embed_text; the worker embeds the images.
ClientTextEmbedder = ClientEmbedder


def memory_class():
    return ObjectMemory


def observe_fn():
    return observe


def make_in_view_fn():
    return make_in_view


def median_depth_fn():
    return median_depth


def find_fn():
    return find


def goal_for_fn():
    return goal_for


def vision_client(url, timeout=10.0):
    return VisionClient(url, timeout=timeout)


def client_verifier(client):
    return ClientVerifier(client)


# ---------------------------------------------------------------- JPEG pass-through
def _normalize(v):
    v = np.asarray(v, dtype=np.float32)
    n = float(np.linalg.norm(v))
    return v / n if n > 0 else v


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
    """POST /detect_embed with the camera's JPEG bytes as they are (no decode on the ROS side).

    jpeg=None lets the worker read its own camera.
    """
    body = {} if jpeg is None else {"image_jpeg_b64": base64.b64encode(bytes(jpeg)).decode("ascii")}
    return parse_detections(_post(url, "/detect_embed", body, timeout))


# ---------------------------------------------------------------- drawing
def draw_map_fn():
    """objmem.viz.draw_map, or plain_draw_map when PIL is not installed."""
    from objmem.viz import draw_map
    try:
        import PIL  # noqa: F401  (viz imports it lazily; check now, not on the first request)
        return draw_map
    except ImportError:
        if "PIL" not in FALLBACKS:
            FALLBACKS.append("PIL")
        return plain_draw_map


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


def plain_draw_map(items, robot_pose=None, occupancy=None, path=None):
    """Objects as squares colored by p (red low, green high), robot in blue. No labels, no PIL."""
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
    """Optional parts that are missing (only "PIL" can be listed)."""
    draw_map_fn()
    return list(FALLBACKS)
