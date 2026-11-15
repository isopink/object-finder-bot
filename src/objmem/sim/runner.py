"""Run the real objmem pipeline in the toy world.

    sim = Sim(mode="depth", seed=0)        # real ObjectMemory, geometry.observe, search.find
    sim.patrol()                            # drive the patrol path and remember objects
    result = sim.ask("Where is the blue mug?")
    sim.world.move("blue_mug", 5.0, 0.65)

`memory="baseline"` swaps in the BaselineMemory (no probability, no fusion);
`ask(..., label_search=True)` runs label-match search instead of CLIP search.
Seeded runs are deterministic.
"""
import copy
import math
import os
import shutil
import tempfile
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

import numpy as np

from objmem import geometry, search
from objmem.memory import ObjectMemory
from objmem.sim.baseline import BaselineMemory, LabelQueryMemory
from objmem.sim.sensors import LabelVerifier, SimCamera, SimNavigator, SimVerifier, query_label
from objmem.sim.world import SimEmbedder, ToyWorld, patrol_path
from objmem.types import MemoryItem, Params, Pose2D, SearchResult

HOME = Pose2D(3.5, 2.5, 0.0)


def sim_params(mode: str = "depth", base: Optional[Params] = None) -> Params:
    """Params for the toy world.

    hfov is clipped to the field of view the intrinsics actually give
    (2 atan(img_w / 2 fx)), so in_view() never reports points the image cannot
    contain even when a config sets a wider hfov.
    """
    p = copy.deepcopy(base) if base is not None else Params()
    p.camera_mode = mode
    p.hfov = min(float(p.hfov), intrinsic_hfov(p))
    return p


def intrinsic_hfov(p: Params) -> float:
    return 2.0 * math.atan(0.5 * float(p.img_w) / float(p.fx))


@dataclass
class PatrolStats:
    frames: int = 0
    detections: int = 0
    observations: int = 0


class Sim:
    """One toy world with one memory, camera, navigator, and verifier."""

    def __init__(self, mode: str = "depth", seed: int = 0, memory: str = "prob",
                 params: Optional[Params] = None, world: Optional[ToyWorld] = None, **camera_kw):
        self.mode = mode
        self.seed = seed
        self.params = sim_params(mode, params)
        self.world = world if world is not None else ToyWorld(seed=seed)
        self.camera = SimCamera(self.world, self.params, mode=mode, seed=seed, **camera_kw)
        self.navigator = SimNavigator(self.world, seed=seed)
        self.verifier = SimVerifier(self.world, self.params, seed=seed)
        self.label_verifier = LabelVerifier(self.world, self.params, seed=seed)
        self.embedder = SimEmbedder(self.world.space)
        if memory == "prob":
            self.memory = ObjectMemory(self.params)
        elif memory == "baseline":
            self.memory = BaselineMemory(self.params)
        else:
            raise ValueError("memory must be 'prob' or 'baseline'")
        self.memory_kind = memory
        self.in_view = geometry.make_in_view(self.params)
        self.world.set_robot(HOME)

    # ---------------------------------------------------------- patrol
    def observe_here(self, pose: Optional[Pose2D] = None) -> Tuple[int, int]:
        """One frame at the current (or given) pose: detect, place, update memory."""
        pose = pose or self.world.robot
        t = self.world.t
        dets = self.camera.detect(pose)
        obs = [o for o in (geometry.observe(d, pose, self.params, t) for d in dets) if o is not None]
        self.memory.update_frame(obs, pose, self.in_view, t)
        return len(dets), len(obs)

    def patrol(self, part: str = "full", rounds: int = 1, dwell: float = 2.0, speed: float = 0.2) -> PatrolStats:
        stats = PatrolStats()
        for _ in range(rounds):
            for pose in patrol_path(self.world, part):
                r = self.world.robot
                self.world.advance(math.hypot(pose.x - r.x, pose.y - r.y) / speed + dwell)
                self.world.set_robot(pose)
                nd, no = self.observe_here(pose)
                stats.frames += 1
                stats.detections += nd
                stats.observations += no
        return stats

    # ---------------------------------------------------------- search
    def ask(self, text: str, label_search: bool = False, log_path: Optional[str] = None,
            on_status: Optional[Callable[[str], None]] = None) -> SearchResult:
        memory = LabelQueryMemory(self.memory, query_label(text)) if label_search else self.memory
        verifier = self.label_verifier if label_search else self.verifier
        return search.find(text, memory, self.embedder, self.navigator, verifier, self.params,
                           clock=self.world.clock, log_path=log_path, on_status=on_status)

    def candidates(self, text: str):
        return self.memory.query(self.embedder.embed_text(text), self.world.t)

    # ---------------------------------------------------------- snapshots
    def snapshot(self):
        """State needed to rerun a query from the same starting point."""
        return (clone_memory(self.memory, self.params), self.world.t, copy.deepcopy(self.world.robot))

    def restore(self, snap) -> None:
        mem, t, pose = snap
        self.memory = clone_memory(mem, self.params)
        self.world.t = t
        self.world.robot = copy.deepcopy(pose)

    def item_near(self, name: str, radius: float = 0.5) -> Optional[MemoryItem]:
        """The memory closest to an object's true position, if within radius."""
        o = self.world.object(name)
        best, bd = None, radius
        for it in self.memory.items:
            dist = float(np.hypot(it.mu[0] - o.x, it.mu[1] - o.y))
            if dist <= bd:
                best, bd = it, dist
        return best


def clone_memory(memory, params: Params):
    """Copy a memory through its own save/load (ObjectMemory holds a lock and cannot be deep-copied)."""
    folder = tempfile.mkdtemp(prefix="objmem_sim_")
    try:
        path = os.path.join(folder, "m.npz")
        memory.save(path)
        return type(memory).load(path, params)
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def distance(item: Optional[MemoryItem], xy: Tuple[float, float]) -> float:
    if item is None:
        return float("inf")
    return float(np.hypot(float(item.mu[0]) - xy[0], float(item.mu[1]) - xy[1]))


def load_queries(path: Optional[str] = None) -> List[Dict[str, str]]:
    """data/queries.yaml -> [{"text": ..., "target": ...}]."""
    import yaml
    if path is None:
        path = os.path.join(repo_root(), "data", "queries.yaml")
    with open(path, "r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    return [{"text": str(q["text"]), "target": str(q["target"])} for q in data.get("queries", [])]


def repo_root() -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.normpath(os.path.join(here, "..", "..", ".."))
