"""Probabilistic object memory (proposal sections 4.2 to 4.4).

Each memory holds a position Gaussian (mu, cov), a CLIP image embedding, and an
existence confidence p. ``update_frame`` fuses one camera frame of observations:

* association: an observation and a memory are the same object when the
  Mahalanobis distance (item cov + observation cov) is at most ``maha_thresh``
  and the CLIP cosine is at least ``cos_thresh``; one-to-one, greedy by
  Mahalanobis distance;
* matched: Kalman update (depth mode, ``bearing is None``) or an iterated EKF
  update with the scalar bearing measured from ``observation.view_pose``
  (nodepth mode, std ``sigma_bearing``), then the positive Bayes update;
* memories in view but unmatched: the negative Bayes update;
* unmatched observations: new memories with ``p_init``.

Three optional rules keep one object from becoming several memories (each is
off at 0, the default):

* ``cos_thresh_same_label``: the cosine gate used instead of ``cos_thresh`` when
  the observation and the memory carry the same detector label (the same object
  seen from another side can fall below the plain gate);
* ``merge_dist``: after every frame, two memories that pass the cosine gate, do
  not carry different labels, and lie closer than this are merged into one;
* ``pos_std_min``: a floor on the position standard deviation after fusion. A
  static Kalman filter shrinks cov toward zero with every look, below the pose
  error of the robot that repeated looks do not average away.

The first two lean on position instead of appearance, so they apply only when
both positions are known: largest variance at most ``pos_cov_max``. A nodepth
memory that is still a long ray keeps the plain gate and is not merged (in the
toy world the looser gate fused two different mugs along one ray).

``p_update_dist`` (off at 0, the default) spaces the Bayes updates of p: a memory
gets its next positive or negative update only after the robot has moved this far
from where that memory got its last one. Frames taken a few centimeters apart
show the same view, so they are one piece of evidence, not several. Position and
embedding are still fused from every frame; the re-check of the finder
(``mark_found`` / ``mark_not_found``) always counts.

``d_by_range`` (empty by default) replaces the one number ``d`` by a table measured on
the robot: P(detect | present) for the distance between the camera and the remembered
place. A cup 3.5 m away is found far less often than one 1 m away, so missing it there
says little. The value never goes below ``f``: where the detector finds a present object
no more often than an absent one, a look is no evidence either way. ``evidence_log``
names a JSON-lines file that gets one line per frame with every remembered place that
was looked at (distance, found or not); scripts/fit_detection_range.py turns it into
the table. The re-check of the finder keeps the plain ``d``.

Time decay ``p <- 0.5 + (p - 0.5) exp(-dt / tau)`` is applied lazily: every
memory remembers the time its p was last decayed to, so the same interval is
never decayed twice, whichever method triggers it.

The class is thread-safe (one re-entrant lock) so that the ROS observer and
finder can share one instance in one process.
"""
import json
import math
import os
import threading
from typing import Dict, List, Optional, Tuple

import numpy as np

from objmem.geometry import camera_position
from objmem.types import Candidate, InView, MemoryItem, Observation, Params, Pose2D

_P_EPS = 1e-6
_EKF_ITERS = 10


def _normalize(v: np.ndarray) -> np.ndarray:
    v = np.asarray(v, dtype=np.float32).reshape(-1)
    n = float(np.linalg.norm(v))
    if n <= 0.0:
        return v
    return (v / n).astype(np.float32)


def _wrap(a: float) -> float:
    return (a + math.pi) % (2.0 * math.pi) - math.pi


def _sym(m: np.ndarray) -> np.ndarray:
    return 0.5 * (m + m.T)


def bayes_positive(p: float, d: float, f: float) -> float:
    """Location in view and detected: p <- d p / (d p + f (1 - p))."""
    num = d * p
    den = num + f * (1.0 - p)
    return _clip_p(num / den if den > 0 else p)


def bayes_negative(p: float, d: float, f: float) -> float:
    """Location in view and not detected: p <- (1-d) p / ((1-d) p + (1-f)(1-p))."""
    num = (1.0 - d) * p
    den = num + (1.0 - f) * (1.0 - p)
    return _clip_p(num / den if den > 0 else p)


def detect_prob(r: float, params: Params) -> float:
    """P(detect | present) for an object r meters from the camera: ``params.d``, or the row of
    ``params.d_by_range`` ([up to this distance, P]) that covers r (beyond the last row: its
    value). Never below ``params.f``."""
    d = float(params.d)
    table = sorted((float(row[0]), float(row[1])) for row in (params.d_by_range or []))
    if table:
        d = table[-1][1]
        for upper, value in table:
            if r <= upper:
                d = value
                break
    return max(d, float(params.f))


def time_decay(p: float, dt: float, tau: float) -> float:
    """p <- 0.5 + (p - 0.5) exp(-dt / tau). No change for dt <= 0."""
    if dt <= 0.0 or tau <= 0.0:
        return p
    return 0.5 + (p - 0.5) * math.exp(-dt / tau)


def _clip_p(p: float) -> float:
    return float(min(max(p, _P_EPS), 1.0 - _P_EPS))


def kalman_update(mu: np.ndarray, cov: np.ndarray, z: np.ndarray, R: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """Static-object Kalman update: K = S (S + R)^-1, mu += K (z - mu), S = (I - K) S."""
    mu = np.asarray(mu, dtype=float)
    cov = np.asarray(cov, dtype=float)
    K = cov.dot(np.linalg.inv(cov + np.asarray(R, dtype=float)))
    mu_new = mu + K.dot(np.asarray(z, dtype=float) - mu)
    cov_new = _sym((np.eye(2) - K).dot(cov))
    return mu_new, cov_new


def bearing_update(mu: np.ndarray, cov: np.ndarray, origin: np.ndarray, bearing: float,
                   sigma: float, iters: int = _EKF_ITERS) -> Tuple[np.ndarray, np.ndarray]:
    """Iterated EKF update with one bearing measurement h(x) = atan2(y - oy, x - ox).

    ``iters=1`` is the plain EKF. Iterating re-linearizes around the updated
    estimate, which matters when a nodepth memory is still a long ray.
    """
    mu0 = np.asarray(mu, dtype=float)
    cov0 = np.asarray(cov, dtype=float)
    origin = np.asarray(origin, dtype=float)
    R = float(sigma) ** 2
    x = mu0.copy()
    H = None
    K = None
    for _ in range(max(1, iters)):
        dx, dy = x - origin
        r2 = dx * dx + dy * dy
        if r2 < 1e-9:
            return mu0, cov0  # measurement origin on top of the estimate: no information
        H = np.array([-dy / r2, dx / r2])
        S = float(H.dot(cov0).dot(H)) + R
        K = cov0.dot(H) / S
        h = math.atan2(dy, dx)
        innov = _wrap(bearing - h - float(H.dot(mu0 - x)))
        x_new = mu0 + K * innov
        if np.linalg.norm(x_new - x) < 1e-9:
            x = x_new
            break
        x = x_new
    cov_new = _sym((np.eye(2) - np.outer(K, H)).dot(cov0))
    return x, cov_new


def floor_cov(cov: np.ndarray, std_min: float) -> np.ndarray:
    """Raise every eigenvalue of cov below std_min^2 to std_min^2 (std_min <= 0: unchanged)."""
    if std_min <= 0.0:
        return cov
    w, v = np.linalg.eigh(_sym(np.asarray(cov, dtype=float)))
    lo = float(std_min) ** 2
    if float(w.min()) >= lo:
        return cov
    return _sym((v * np.maximum(w, lo)).dot(v.T))


def mahalanobis(mu_a: np.ndarray, cov_a: np.ndarray, mu_b: np.ndarray, cov_b: np.ndarray) -> float:
    diff = np.asarray(mu_a, dtype=float) - np.asarray(mu_b, dtype=float)
    S = np.asarray(cov_a, dtype=float) + np.asarray(cov_b, dtype=float)
    try:
        d2 = float(diff.dot(np.linalg.solve(S, diff)))
    except np.linalg.LinAlgError:
        return float("inf")
    return math.sqrt(max(d2, 0.0))


class ObjectMemory:
    """Implements objmem.types.MemoryAPI."""

    def __init__(self, params: Optional[Params] = None):
        self.params = params if params is not None else Params()
        self._items = []  # type: List[MemoryItem]
        self._t_p = {}  # type: Dict[int, float]  # time each item's p was last decayed to
        self._next_id = 0
        self._merged_into = {}  # type: Dict[int, int]  # id removed by a merge -> id that absorbed it
        self._p_xy = {}  # type: Dict[int, Tuple[float, float]]  # robot position at each item's last update of p
        self._evidence_warned = False
        self._lock = threading.RLock()

    # ------------------------------------------------------------ access
    @property
    def items(self) -> List[MemoryItem]:
        with self._lock:
            return list(self._items)

    def __len__(self) -> int:
        return len(self._items)

    def get(self, item_id: int) -> Optional[MemoryItem]:
        with self._lock:
            item_id = self._merged_into.get(item_id, item_id)
            for item in self._items:
                if item.id == item_id:
                    return item
            return None

    def _pos_known(self, cov: np.ndarray) -> bool:
        return float(np.linalg.eigvalsh(_sym(np.asarray(cov, dtype=float))).max()) <= self.params.pos_cov_max

    def _cos_gate(self, label_a: Optional[str], cov_a: np.ndarray, label_b: Optional[str], cov_b: np.ndarray) -> float:
        pr = self.params
        if (pr.cos_thresh_same_label > 0.0 and label_a is not None and label_a == label_b
                and self._pos_known(cov_a) and self._pos_known(cov_b)):
            return float(pr.cos_thresh_same_label)
        return float(pr.cos_thresh)

    def decay_to(self, t: float) -> None:
        """Decay every p to time t (idempotent for the same t)."""
        with self._lock:
            for item in self._items:
                self._decay_item(item, t)

    def _decay_item(self, item: MemoryItem, t: float) -> None:
        t0 = self._t_p.get(item.id, item.t_last)
        if t > t0:
            item.p = _clip_p(time_decay(item.p, t - t0, self.params.tau))
            self._t_p[item.id] = t

    # ------------------------------------------------------------ update
    def add(self, obs: Observation, t: Optional[float] = None) -> MemoryItem:
        """Create a new memory from one observation (p = p_init)."""
        with self._lock:
            t = obs.t if t is None else t
            item = MemoryItem(
                id=self._next_id,
                mu=np.asarray(obs.mu, dtype=float).copy(),
                cov=_sym(np.asarray(obs.cov, dtype=float)),
                embedding=_normalize(obs.embedding),
                p=_clip_p(self.params.p_init),
                t_last=float(t),
                n_obs=1,
                view_pose=Pose2D(obs.view_pose.x, obs.view_pose.y, obs.view_pose.yaw),
                label=obs.label,
            )
            self._next_id += 1
            self._items.append(item)
            self._t_p[item.id] = float(t)
            return item

    def associate(self, observations: List[Observation]) -> List[Tuple[int, int]]:
        """One-to-one (observation index, item index) pairs that pass both gates,
        chosen greedily by Mahalanobis distance (ties: higher cosine first).
        The cosine gate is ``cos_thresh``, or ``cos_thresh_same_label`` for equal labels
        and known positions."""
        with self._lock:
            pr = self.params
            pairs = []
            for i, obs in enumerate(observations):
                e = _normalize(obs.embedding)
                for j, item in enumerate(self._items):
                    cos = float(np.dot(e, item.embedding))
                    if cos < self._cos_gate(obs.label, obs.cov, item.label, item.cov):
                        continue
                    dm = mahalanobis(obs.mu, obs.cov, item.mu, item.cov)
                    if dm > pr.maha_thresh:
                        continue
                    pairs.append((dm, -cos, i, j))
            pairs.sort()
            used_obs, used_items, out = set(), set(), []
            for _, _, i, j in pairs:
                if i in used_obs or j in used_items:
                    continue
                used_obs.add(i)
                used_items.add(j)
                out.append((i, j))
            return out

    def _fuse(self, item: MemoryItem, obs: Observation, t: float) -> None:
        pr = self.params
        if obs.bearing is None:
            item.mu, item.cov = kalman_update(item.mu, item.cov, obs.mu, obs.cov)
        else:
            origin = np.array([obs.view_pose.x, obs.view_pose.y], dtype=float)
            item.mu, item.cov = bearing_update(item.mu, item.cov, origin, float(obs.bearing), pr.sigma_bearing)
        item.cov = floor_cov(item.cov, pr.pos_std_min)
        n = item.n_obs
        item.embedding = _normalize(item.embedding.astype(float) * n + _normalize(obs.embedding).astype(float))
        item.n_obs = n + 1
        item.t_last = float(t)
        item.view_pose = Pose2D(obs.view_pose.x, obs.view_pose.y, obs.view_pose.yaw)
        if obs.label is not None:
            item.label = obs.label

    def _p_evidence(self, item: MemoryItem, pose: Pose2D) -> bool:
        """True when this frame counts as new evidence for the item's p (and notes the robot position)."""
        here = (float(pose.x), float(pose.y))
        last = self._p_xy.get(item.id)
        if (self.params.p_update_dist > 0.0 and last is not None
                and math.hypot(here[0] - last[0], here[1] - last[1]) < self.params.p_update_dist):
            return False
        self._p_xy[item.id] = here
        return True

    def update_frame(self, observations: List[Observation], pose: Pose2D, in_view: InView, t: float) -> None:
        with self._lock:
            pr = self.params
            self.decay_to(t)
            matches = self.associate(observations)
            matched_obs = set(i for i, _ in matches)
            matched_items = set(j for _, j in matches)
            cam = camera_position(pose, pr)
            looks = []  # (item, distance, found, counted for p, new) for the evidence log

            def dist(item):
                return math.hypot(float(item.mu[0]) - float(cam[0]), float(item.mu[1]) - float(cam[1]))

            for i, j in matches:
                item = self._items[j]
                self._fuse(item, observations[i], t)
                r, counted = dist(item), self._p_evidence(item, pose)
                if counted:
                    item.p = bayes_positive(item.p, detect_prob(r, pr), pr.f)
                looks.append((item, r, True, counted, False))
            for j, item in enumerate(self._items):
                if j in matched_items:
                    continue
                if in_view(item.mu, pose):
                    r, counted = dist(item), self._p_evidence(item, pose)
                    if counted:
                        item.p = bayes_negative(item.p, detect_prob(r, pr), pr.f)
                    looks.append((item, r, False, counted, False))
            for i, obs in enumerate(observations):
                if i not in matched_obs:
                    item = self.add(obs, t)
                    self._p_xy[item.id] = (float(pose.x), float(pose.y))
                    looks.append((item, dist(item), True, True, True))
            if pr.evidence_log and looks:
                self._write_evidence(t, pose, len(observations), looks)
            if pr.merge_dist > 0.0:
                self.merge_duplicates(t)

    def _write_evidence(self, t: float, pose: Pose2D, n_obs: int, looks) -> None:
        """One JSON line: every remembered place looked at in this frame. A failure to write
        is reported once and never stops the update."""
        try:
            rec = {"t": round(float(t), 3),
                   "pose": [round(float(pose.x), 3), round(float(pose.y), 3), round(float(pose.yaw), 4)],
                   "n_obs": int(n_obs), "items": []}
            for item, r, found, counted, new in looks:
                row = {"id": int(item.id), "label": item.label, "r": round(float(r), 3),
                       "hit": int(found), "counted": int(counted), "p": round(float(item.p), 4)}
                if new:
                    row["new"] = 1
                rec["items"].append(row)
            path = self.params.evidence_log
            folder = os.path.dirname(os.path.abspath(path))
            if not os.path.isdir(folder):
                os.makedirs(folder)
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec) + "\n")
        except Exception as exc:  # noqa: BLE001 - the log is for people
            if not self._evidence_warned:
                self._evidence_warned = True
                print("objmem: cannot write the evidence log {!r}: {}".format(self.params.evidence_log, exc), flush=True)

    def _mergeable(self, a: MemoryItem, b: MemoryItem) -> Optional[float]:
        """Distance (m) between two memories that count as one object, else None."""
        if a.label is not None and b.label is not None and a.label != b.label:
            return None
        dist = float(np.linalg.norm(np.asarray(a.mu, dtype=float) - np.asarray(b.mu, dtype=float)))
        if dist > self.params.merge_dist:
            return None
        if not (self._pos_known(a.cov) and self._pos_known(b.cov)):
            return None
        if float(np.dot(a.embedding, b.embedding)) < self._cos_gate(a.label, a.cov, b.label, b.cov):
            return None
        return dist

    def merge_duplicates(self, t: Optional[float] = None) -> List[Tuple[int, int]]:
        """Merge memories of one object: closer than ``merge_dist``, positions known,
        not differently labeled, cosine above the gate. Closest pair first, until no pair is left.

        The memory with more observations stays and absorbs the other: positions
        fused as two independent estimates, embeddings averaged by n_obs, p the
        larger of the two (both decayed to ``t`` when given), n_obs added.
        Returns (kept id, removed id) pairs; ``get(removed id)`` gives the kept memory.
        """
        merged = []  # type: List[Tuple[int, int]]
        with self._lock:
            if self.params.merge_dist <= 0.0:
                return merged
            while True:
                best = None
                for i in range(len(self._items)):
                    for j in range(i + 1, len(self._items)):
                        dist = self._mergeable(self._items[i], self._items[j])
                        if dist is not None and (best is None or dist < best[0]):
                            best = (dist, i, j)
                if best is None:
                    return merged
                a, b = self._items[best[1]], self._items[best[2]]
                keep, drop = (a, b) if (-a.n_obs, a.id) <= (-b.n_obs, b.id) else (b, a)
                if t is not None:
                    self._decay_item(keep, t)
                    self._decay_item(drop, t)
                keep.mu, keep.cov = kalman_update(keep.mu, keep.cov, drop.mu, drop.cov)
                keep.cov = floor_cov(keep.cov, self.params.pos_std_min)
                keep.embedding = _normalize(keep.embedding.astype(float) * keep.n_obs
                                            + drop.embedding.astype(float) * drop.n_obs)
                keep.n_obs += drop.n_obs
                keep.p = max(keep.p, drop.p)
                if drop.t_last > keep.t_last:
                    keep.t_last = drop.t_last
                    keep.view_pose = Pose2D(drop.view_pose.x, drop.view_pose.y, drop.view_pose.yaw)
                if keep.label is None:
                    keep.label = drop.label
                self._t_p[keep.id] = max(self._t_p.get(keep.id, keep.t_last), self._t_p.get(drop.id, drop.t_last))
                self._items = [it for it in self._items if it.id != drop.id]
                self._t_p.pop(drop.id, None)
                self._p_xy.pop(drop.id, None)
                for old, new in list(self._merged_into.items()):
                    if new == drop.id:
                        self._merged_into[old] = keep.id
                self._merged_into[drop.id] = keep.id
                merged.append((keep.id, drop.id))

    # ------------------------------------------------------------ search
    def query(self, text_embedding: np.ndarray, t: float, k: Optional[int] = None) -> List[Candidate]:
        with self._lock:
            k = self.params.top_k if k is None else k
            if not self._items or k <= 0:
                return []
            self.decay_to(t)
            q = _normalize(text_embedding).astype(float)
            sims = np.array([float(np.dot(q, it.embedding)) for it in self._items])
            z = sims / float(self.params.T)
            w = np.exp(z - z.max())
            w = w / w.sum()
            scores = w * np.array([it.p for it in self._items])
            order = sorted(range(len(self._items)), key=lambda j: (-scores[j], self._items[j].id))
            return [Candidate(item=self._items[j], sim=float(sims[j]), score=float(scores[j])) for j in order[:k]]

    def mark_found(self, item_id: int, t: float) -> None:
        """Re-check passed at the remembered place: positive Bayes update."""
        with self._lock:
            item = self.get(item_id)
            if item is None:
                return
            self._decay_item(item, t)
            item.p = bayes_positive(item.p, self.params.d, self.params.f)
            item.t_last = max(item.t_last, float(t))

    def mark_not_found(self, item_id: int, t: float) -> None:
        """Re-check failed at the remembered place: negative Bayes update."""
        with self._lock:
            item = self.get(item_id)
            if item is None:
                return
            self._decay_item(item, t)
            item.p = bayes_negative(item.p, self.params.d, self.params.f)

    def remove(self, item_id: int) -> None:
        with self._lock:
            self._items = [it for it in self._items if it.id != item_id]
            self._t_p.pop(item_id, None)
            self._p_xy.pop(item_id, None)

    # ------------------------------------------------------------ persistence
    def save(self, path: str) -> None:
        """Write every field to one .npz file (atomic replace)."""
        with self._lock:
            items = self._items
            n = len(items)
            dim = int(items[0].embedding.shape[0]) if n else 0
            data = {
                "version": np.array(1),
                "next_id": np.array(self._next_id, dtype=np.int64),
                "ids": np.array([it.id for it in items], dtype=np.int64),
                "mu": np.array([it.mu for it in items], dtype=float).reshape(n, 2),
                "cov": np.array([it.cov for it in items], dtype=float).reshape(n, 2, 2),
                "embedding": np.array([it.embedding for it in items], dtype=np.float32).reshape(n, dim),
                "p": np.array([it.p for it in items], dtype=float),
                "t_last": np.array([it.t_last for it in items], dtype=float),
                "t_p": np.array([self._t_p.get(it.id, it.t_last) for it in items], dtype=float),
                "n_obs": np.array([it.n_obs for it in items], dtype=np.int64),
                "view_pose": np.array([[it.view_pose.x, it.view_pose.y, it.view_pose.yaw] for it in items],
                                      dtype=float).reshape(n, 3),
                "has_label": np.array([it.label is not None for it in items], dtype=bool),
                "labels": np.array([it.label or "" for it in items], dtype=str),
            }
            folder = os.path.dirname(os.path.abspath(path))
            if not os.path.isdir(folder):
                os.makedirs(folder)
            tmp = path + ".tmp"
            with open(tmp, "wb") as fh:
                np.savez(fh, **data)
            os.replace(tmp, path)

    @classmethod
    def load(cls, path: str, params: Optional[Params] = None) -> "ObjectMemory":
        mem = cls(params)
        with np.load(path, allow_pickle=False) as z:
            mem._next_id = int(z["next_id"])
            for j in range(len(z["ids"])):
                vp = z["view_pose"][j]
                item = MemoryItem(
                    id=int(z["ids"][j]),
                    mu=np.array(z["mu"][j], dtype=float),
                    cov=np.array(z["cov"][j], dtype=float),
                    embedding=np.array(z["embedding"][j], dtype=np.float32),
                    p=float(z["p"][j]),
                    t_last=float(z["t_last"][j]),
                    n_obs=int(z["n_obs"][j]),
                    view_pose=Pose2D(float(vp[0]), float(vp[1]), float(vp[2])),
                    label=str(z["labels"][j]) if bool(z["has_label"][j]) else None,
                )
                mem._items.append(item)
                mem._t_p[item.id] = float(z["t_p"][j])
        return mem
