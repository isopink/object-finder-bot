"""Sim camera + detector, navigator, and verifiers for the toy world."""
import math
from typing import List, Optional, Tuple

import numpy as np

from objmem.types import DEFAULT_BACKGROUND_PROMPTS, Detection, Params, Pose2D
from objmem.sim.world import EMB_DIM, SYNONYMS, ToyWorld, tokenize

COCO_LABELS = ["cup", "bottle", "laptop", "book", "cell phone", "keyboard", "mouse", "remote"]


def _rot(yaw: float, pitch: float) -> np.ndarray:
    """Rotation base <- camera body (x forward, y left, z up). Positive pitch = tilted down."""
    cy, sy = math.cos(yaw), math.sin(yaw)
    cp, sp = math.cos(pitch), math.sin(pitch)
    rz = np.array([[cy, -sy, 0.0], [sy, cy, 0.0], [0.0, 0.0, 1.0]])
    ry = np.array([[cp, 0.0, sp], [0.0, 1.0, 0.0], [-sp, 0.0, cp]])
    return rz @ ry


def map_to_optical(p_map: np.ndarray, pose: Pose2D, params: Params) -> np.ndarray:
    """3D map point -> camera optical frame (x right, y down, z forward)."""
    c, s = math.cos(pose.yaw), math.sin(pose.yaw)
    dx, dy = p_map[0] - pose.x, p_map[1] - pose.y
    p_base = np.array([c * dx + s * dy, -s * dx + c * dy, p_map[2]])
    cam = np.array([params.cam_x, params.cam_y, params.cam_z])
    body = _rot(params.cam_yaw, params.cam_pitch).T @ (p_base - cam)
    return np.array([-body[1], -body[2], body[0]])


def camera_xy_yaw(pose: Pose2D, params: Params) -> Tuple[float, float, float]:
    c, s = math.cos(pose.yaw), math.sin(pose.yaw)
    x = pose.x + c * params.cam_x - s * params.cam_y
    y = pose.y + s * params.cam_x + c * params.cam_y
    return x, y, pose.yaw + params.cam_yaw


class SimCamera:
    """Camera + fake detector over the toy world.

    `detect(pose)` returns objmem Detections as the vision worker would: box, label,
    conf, embedding, and depth_m (depth mode) or None (nodepth mode).
    """

    def __init__(self, world: ToyWorld, params: Params, mode: Optional[str] = None,
                 seed: int = 0, det_rate: float = 0.9, fp_rate: float = 0.15,
                 pixel_noise: float = 3.0, emb_noise: float = 0.25, max_range: float = 4.0):
        self.world = world
        self.params = params
        self.mode = mode or params.camera_mode
        if self.mode not in ("depth", "nodepth"):
            raise ValueError("mode must be 'depth' or 'nodepth'")
        self.rng = np.random.default_rng(seed)
        self.det_rate = det_rate
        self.fp_rate = fp_rate
        self.pixel_noise = pixel_noise
        self.emb_noise = emb_noise
        self.max_range = max_range

    def project(self, name: str, pose: Pose2D) -> Optional[Tuple[float, float, float]]:
        """(u, v, z) of an object's center, or None when it is outside the image."""
        p = self.params
        o = self.world.object(name)
        q = map_to_optical(np.array([o.x, o.y, o.z]), pose, p)
        if q[2] <= 0.05:
            return None
        u = p.fx * q[0] / q[2] + p.cx
        v = p.fy * q[1] / q[2] + p.cy
        if not (0 <= u < p.img_w and 0 <= v < p.img_h):
            return None
        return u, v, float(q[2])

    def visible(self, pose: Pose2D) -> List[str]:
        out = []
        for name in self.world.objects:
            pr = self.project(name, pose)
            if pr is not None and pr[2] <= self.max_range:
                out.append(name)
        return out

    def _box(self, u: float, v: float, z: float, size: float) -> Tuple[int, int, int, int]:
        p = self.params
        half = max(4.0, p.fx * size / 2.0 / z)
        l = int(max(0, min(p.img_w - 1, round(u - half))))
        r = int(max(0, min(p.img_w - 1, round(u + half))))
        t = int(max(0, min(p.img_h - 1, round(v - half))))
        b = int(max(0, min(p.img_h - 1, round(v + half))))
        return l, t, r, b

    def _depth(self, z: float) -> Optional[float]:
        if self.mode != "depth" or not (0.2 <= z <= 6.0):
            return None
        sd = self.params.sigma_range_a + self.params.sigma_range_b * z * z
        return float(z + self.rng.normal(0.0, sd))

    def detect(self, pose: Optional[Pose2D] = None) -> List[Detection]:
        pose = pose or self.world.robot
        dets: List[Detection] = []
        for name in sorted(self.world.objects):
            pr = self.project(name, pose)
            if pr is None or pr[2] > self.max_range:
                continue
            u, v, z = pr
            rate = self.det_rate if z <= 2.5 else self.det_rate * max(0.0, (self.max_range - z) / 1.5)
            if self.rng.random() >= rate:
                continue
            o = self.world.object(name)
            # box center with pixel noise; the box keeps its true size
            un = u + self.rng.normal(0.0, self.pixel_noise)
            vn = v + self.rng.normal(0.0, self.pixel_noise)
            box = self._box(un, vn, z, o.size)
            emb = self.world.space.image_embedding(o, self.rng, self.emb_noise)
            dets.append(Detection(box=box, label=o.coco or "object", conf=float(self.rng.uniform(0.5, 0.95)),
                                  embedding=emb, depth_m=self._depth(z)))
        for _ in range(int(self.rng.poisson(self.fp_rate))):
            p = self.params
            z = float(self.rng.uniform(0.8, 3.5))
            u = float(self.rng.uniform(40, p.img_w - 40))
            v = float(self.rng.uniform(40, p.img_h - 40))
            dets.append(Detection(box=self._box(u, v, z, 0.12), label=str(self.rng.choice(COCO_LABELS)),
                                  conf=float(self.rng.uniform(0.3, 0.6)),
                                  embedding=self.world.space.clutter_embedding(self.rng),
                                  depth_m=self._depth(z)))
        return dets


class SimNavigator:
    """Implements objmem.types.Navigator. Teleports the robot if the goal is free space.

    Goals inside desks, walls, or outside the room fail. `fail_prob` adds random failures.
    The sim clock advances by the travel time.
    """

    def __init__(self, world: ToyWorld, speed: float = 0.2, fail_prob: float = 0.0, seed: int = 0):
        self.world = world
        self.speed = speed
        self.fail_prob = fail_prob
        self.rng = np.random.default_rng(seed + 7)
        self.goals: List[Tuple[Pose2D, bool]] = []

    def go_to(self, pose: Pose2D) -> bool:
        ok = self.world.is_free(pose.x, pose.y)
        if ok and self.fail_prob > 0 and self.rng.random() < self.fail_prob:
            ok = False
        r = self.world.robot
        dist = math.hypot(pose.x - r.x, pose.y - r.y)
        if ok:
            self.world.advance(dist / self.speed + 2.0)
            self.world.set_robot(pose)
        else:
            self.world.advance(5.0)
        self.goals.append((Pose2D(pose.x, pose.y, pose.yaw), ok))
        return ok


def _visible_near(world: ToyWorld, params: Params, verify_range: float) -> List[Tuple[str, float]]:
    """Objects in the camera's horizontal field of view within verify_range: (name, range)."""
    x, y, yaw = camera_xy_yaw(world.robot, params)
    out = []
    for name, o in world.objects.items():
        dx, dy = o.x - x, o.y - y
        r = math.hypot(dx, dy)
        if r > verify_range or r < 0.1:
            continue
        a = math.atan2(dy, dx) - yaw
        a = (a + math.pi) % (2 * math.pi) - math.pi
        if abs(a) <= params.hfov / 2.0:
            out.append((name, r))
    return out


class SimVerifier:
    """Implements objmem.types.Verifier from ground truth near the robot.

    Mimics the live re-check: for each object in view, softmax over [query] +
    background prompts with logit scale `clip_logit_scale`; the best probability
    counts. Background prompts score a constant baseline cosine. Far objects score lower.
    """

    def __init__(self, world: ToyWorld, params: Params, seed: int = 0, verify_range: float = 2.5,
                 bg_cos: float = 0.27, noise: float = 0.01):
        self.world = world
        self.params = params
        self.rng = np.random.default_rng(seed + 11)
        self.verify_range = verify_range
        self.bg_cos = bg_cos
        self.noise = noise
        self.checks: List[Tuple[str, bool, float]] = []

    def check(self, text: str) -> Tuple[bool, float]:
        p = self.params
        space = self.world.space
        q = space.text_embedding(text)
        prompts = [b for b in (getattr(p, "background_prompts", None) or DEFAULT_BACKGROUND_PROMPTS)
                   if b.lower() not in text.lower()]
        best = 0.0
        for name, r in _visible_near(self.world, p, self.verify_range):
            img = space.image_embedding(self.world.object(name))
            cos_q = float(img @ q) - 0.04 * max(0.0, r - 1.2) + self.rng.normal(0.0, self.noise)
            bg = self.bg_cos + self.rng.normal(0.0, self.noise, size=len(prompts))
            logits = p.clip_logit_scale * np.concatenate([[cos_q], bg])
            logits = logits - logits.max()
            prob = float(np.exp(logits[0]) / np.exp(logits).sum())
            best = max(best, prob)
        found = best >= p.found_thresh
        self.checks.append((text, found, best))
        return found, best


def query_label(text: str) -> Optional[str]:
    """The fixed detector class a query asks for, or None (e.g. 'charger' has no class)."""
    table = {"mug": "cup", "cup": "cup", "tumbler": "bottle", "bottle": "bottle", "laptop": "laptop",
             "book": "book", "phone": "cell phone"}
    words = tokenize(text)
    for i, w in enumerate(words):
        if w in ("next", "near", "beside", "behind", "by"):
            break
        a = SYNONYMS.get(w)
        if a in table:
            return table[a]
    return None


class LabelVerifier:
    """Re-check for label-match search: found when an object of the query's class is in view."""

    def __init__(self, world: ToyWorld, params: Params, seed: int = 0, verify_range: float = 2.5,
                 det_rate: float = 0.9):
        self.world = world
        self.params = params
        self.rng = np.random.default_rng(seed + 13)
        self.verify_range = verify_range
        self.det_rate = det_rate

    def check(self, text: str) -> Tuple[bool, float]:
        label = query_label(text)
        if label is None:
            return False, 0.0
        for name, _ in _visible_near(self.world, self.params, self.verify_range):
            if self.world.object(name).coco == label and self.rng.random() < self.det_rate:
                return True, 1.0
        return False, 0.0


__all__ = ["SimCamera", "SimNavigator", "SimVerifier", "LabelVerifier", "query_label",
           "map_to_optical", "camera_xy_yaw", "EMB_DIM"]
