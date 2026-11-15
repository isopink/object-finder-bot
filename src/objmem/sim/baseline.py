"""Comparison memories for the evaluation.

BaselineMemory: the "without probabilistic memory" side. Every observation is
appended as its own memory; no position fusion, no existence confidence, and the
search ranks by CLIP similarity only.

LabelQueryMemory: label-match search (fixed-class detector, no CLIP). It wraps
any memory and ranks the items whose detector label is the query's class.
"""
from typing import List, Optional

import numpy as np

from objmem.types import Candidate, InView, MemoryItem, Observation, Params, Pose2D


def _softmax(x: np.ndarray) -> np.ndarray:
    if x.size == 0:
        return x
    e = np.exp(x - x.max())
    return e / e.sum()


class BaselineMemory:
    """Implements objmem.types.MemoryAPI with no probability and no fusion."""

    def __init__(self, params: Optional[Params] = None):
        self.params = params or Params()
        self._items: List[MemoryItem] = []

    @property
    def items(self) -> List[MemoryItem]:
        return self._items

    def update_frame(self, observations: List[Observation], pose: Pose2D, in_view: InView, t: float) -> None:
        for ob in observations:
            self._items.append(MemoryItem(
                id=len(self._items), mu=np.asarray(ob.mu, dtype=float).copy(),
                cov=np.asarray(ob.cov, dtype=float).copy(),
                embedding=np.asarray(ob.embedding, dtype=np.float32).copy(), p=1.0, t_last=float(ob.t),
                n_obs=1, view_pose=ob.view_pose, label=ob.label))

    def query(self, text_embedding: np.ndarray, t: float, k: Optional[int] = None) -> List[Candidate]:
        k = self.params.top_k if k is None else k
        if not self._items:
            return []
        E = np.stack([it.embedding for it in self._items]).astype(float)
        sims = E @ np.asarray(text_embedding, dtype=float)
        w = _softmax(sims / self.params.T)
        order = np.argsort(-sims, kind="stable")[:k]
        return [Candidate(item=self._items[i], sim=float(sims[i]), score=float(w[i])) for i in order]

    def mark_found(self, item_id: int, t: float) -> None:
        self._items[item_id].t_last = float(t)

    def mark_not_found(self, item_id: int, t: float) -> None:
        pass  # no confidence to lower

    def save(self, path: str) -> None:
        it = self._items
        np.savez(path,
                 mu=np.array([i.mu for i in it]).reshape(-1, 2),
                 cov=np.array([i.cov for i in it]).reshape(-1, 2, 2),
                 embedding=np.array([i.embedding for i in it], dtype=np.float32).reshape(-1, 512),
                 t_last=np.array([i.t_last for i in it]),
                 view_pose=np.array([[i.view_pose.x, i.view_pose.y, i.view_pose.yaw] for i in it]).reshape(-1, 3),
                 label=np.array([i.label or "" for i in it]))

    @classmethod
    def load(cls, path: str, params: Optional[Params] = None) -> "BaselineMemory":
        m = cls(params)
        d = np.load(path)
        for i in range(len(d["mu"])):
            vp = d["view_pose"][i]
            m._items.append(MemoryItem(id=i, mu=d["mu"][i], cov=d["cov"][i], embedding=d["embedding"][i],
                                       p=1.0, t_last=float(d["t_last"][i]), n_obs=1,
                                       view_pose=Pose2D(float(vp[0]), float(vp[1]), float(vp[2])),
                                       label=str(d["label"][i]) or None))
        return m


class LabelQueryMemory:
    """Label-match search over an existing memory, for one query.

    query() ignores the text embedding and returns the items whose label equals
    the query's detector class, highest confidence first. Everything else is
    passed to the wrapped memory, so mark_not_found still lowers confidence.
    """

    def __init__(self, memory, label: Optional[str]):
        self.memory = memory
        self.label = label

    @property
    def items(self) -> List[MemoryItem]:
        return self.memory.items

    def update_frame(self, observations, pose, in_view, t) -> None:
        self.memory.update_frame(observations, pose, in_view, t)

    def query(self, text_embedding: np.ndarray, t: float, k: Optional[int] = None) -> List[Candidate]:
        params = getattr(self.memory, "params", None) or Params()
        k = params.top_k if k is None else k
        if self.label is None:
            return []
        hits = [it for it in self.memory.items if it.label == self.label]
        hits.sort(key=lambda it: (-it.p, -it.n_obs, it.id))
        return [Candidate(item=it, sim=1.0, score=float(it.p)) for it in hits[:k]]

    def mark_found(self, item_id: int, t: float) -> None:
        self.memory.mark_found(item_id, t)

    def mark_not_found(self, item_id: int, t: float) -> None:
        self.memory.mark_not_found(item_id, t)

    def save(self, path: str) -> None:
        self.memory.save(path)
