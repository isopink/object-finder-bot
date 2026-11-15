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

Time decay ``p <- 0.5 + (p - 0.5) exp(-dt / tau)`` is applied lazily: every
memory remembers the time its p was last decayed to, so the same interval is
never decayed twice, whichever method triggers it.

The class is thread-safe (one re-entrant lock) so that the ROS observer and
finder can share one instance in one process.
"""
import math
import os
import threading
from typing import Dict, List, Optional, Tuple

import numpy as np

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
            for item in self._items:
                if item.id == item_id:
                    return item
            return None

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
        chosen greedily by Mahalanobis distance (ties: higher cosine first)."""
        with self._lock:
            pr = self.params
            pairs = []
            for i, obs in enumerate(observations):
                e = _normalize(obs.embedding)
                for j, item in enumerate(self._items):
                    cos = float(np.dot(e, item.embedding))
                    if cos < pr.cos_thresh:
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
        n = item.n_obs
        item.embedding = _normalize(item.embedding.astype(float) * n + _normalize(obs.embedding).astype(float))
        item.n_obs = n + 1
        item.t_last = float(t)
        item.view_pose = Pose2D(obs.view_pose.x, obs.view_pose.y, obs.view_pose.yaw)
        if obs.label is not None:
            item.label = obs.label

    def update_frame(self, observations: List[Observation], pose: Pose2D, in_view: InView, t: float) -> None:
        with self._lock:
            pr = self.params
            self.decay_to(t)
            matches = self.associate(observations)
            matched_obs = set(i for i, _ in matches)
            matched_items = set(j for _, j in matches)
            for i, j in matches:
                item = self._items[j]
                self._fuse(item, observations[i], t)
                item.p = bayes_positive(item.p, pr.d, pr.f)
            for j, item in enumerate(self._items):
                if j in matched_items:
                    continue
                if in_view(item.mu, pose):
                    item.p = bayes_negative(item.p, pr.d, pr.f)
            for i, obs in enumerate(observations):
                if i not in matched_obs:
                    self.add(obs, t)

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
