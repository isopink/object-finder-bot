"""Toy world: a room with desks, named objects, and synthetic CLIP-like embeddings.

The embeddings imitate CLIP closely enough to exercise the memory and the search:

- every object is a mix of attribute vectors ("blue", "mug", ...) and a unique part,
- an image embedding is the object concept plus an image-modality offset and noise,
- a text embedding is the concept of the attribute words found in the sentence plus a
  text-modality offset, so text-image cosines sit around 0.3 to 0.4 like real CLIP,
- objects that share attributes (two mugs) are closer than unrelated objects.
"""
import copy
import math
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

from objmem.types import Pose2D

EMB_DIM = 512
T0 = 1763251200.0  # sim start time (unix seconds)

# Words that map to an attribute vector. Several words can share one attribute.
SYNONYMS = {
    "mug": "mug", "mugs": "mug", "coffee": "mug",
    "cup": "cup", "cups": "cup", "glass": "cup",
    "straw": "straw",
    "plastic": "plastic", "clear": "clear", "transparent": "clear",
    "charger": "charger", "charging": "charger", "adapter": "charger", "cable": "cable", "brick": "charger",
    "tumbler": "tumbler", "thermos": "tumbler", "flask": "tumbler",
    "metal": "metal", "steel": "metal", "metallic": "metal",
    "laptop": "laptop", "notebook": "laptop", "computer": "laptop",
    "book": "book", "textbook": "book",
    "bottle": "bottle", "water": "water",
    "phone": "phone", "smartphone": "phone", "cellphone": "phone", "mobile": "phone",
    "headphones": "headphones", "headphone": "headphones", "headset": "headphones", "earphones": "headphones",
    "blue": "blue", "red": "red", "green": "green", "black": "black", "white": "white",
    "yellow": "yellow", "silver": "silver", "gray": "silver", "grey": "silver",
    "ceramic": "ceramic", "paper": "paper",
    # background prompt words
    "wall": "wall", "floor": "floor", "ceiling": "ceiling", "desk": "desk", "table": "desk",
    "chair": "chair", "person": "person", "monitor": "monitor", "screen": "monitor",
    "keyboard": "keyboard", "room": "room", "blurry": "blurry",
}
ATTRIBUTES = sorted(set(SYNONYMS.values()))

# Words after these are context ("next to the laptop"), not the object itself.
CONTEXT_WORDS = {"next", "near", "beside", "behind", "by", "under", "left", "right", "front"}
CONTEXT_WEIGHT = 0.3


@dataclass
class Desk:
    name: str
    x0: float
    y0: float
    x1: float
    y1: float
    height: float = 0.75

    def contains(self, x: float, y: float, margin: float = 0.0) -> bool:
        return (self.x0 - margin <= x <= self.x1 + margin) and (self.y0 - margin <= y <= self.y1 + margin)


@dataclass
class SimObject:
    name: str
    attrs: List[str]           # attribute names (values of SYNONYMS)
    coco: Optional[str]        # what a fixed-class detector calls it; None = no such class
    x: float
    y: float
    z: float = 0.8             # height of the object center above the floor (m)
    size: float = 0.12         # apparent width (m)

    @property
    def pos(self) -> np.ndarray:
        return np.array([self.x, self.y], dtype=float)


def default_objects() -> List[SimObject]:
    """Ten desk objects. Names match data/queries.yaml and data/ground_truth.yaml."""
    return [
        SimObject("blue_mug", ["blue", "mug", "ceramic"], "cup", 0.9, 4.35),
        SimObject("red_mug", ["red", "mug", "ceramic"], "cup", 3.5, 4.40),
        SimObject("plastic_cup", ["clear", "plastic", "cup", "straw"], "cup", 1.0, 0.62),
        SimObject("black_charger", ["black", "charger", "cable"], None, 1.9, 0.65, size=0.08),
        SimObject("green_tumbler", ["green", "tumbler", "metal"], "bottle", 4.3, 4.38),
        SimObject("silver_laptop", ["silver", "laptop"], "laptop", 1.5, 0.55, size=0.30),
        SimObject("yellow_book", ["yellow", "book", "paper"], "book", 5.7, 4.40, size=0.20),
        SimObject("water_bottle", ["clear", "plastic", "water", "bottle"], "bottle", 5.2, 0.62),
        SimObject("black_phone", ["black", "phone"], "cell phone", 6.2, 0.60, size=0.08),
        SimObject("white_headphones", ["white", "headphones"], None, 6.3, 4.35, size=0.18),
    ]


def default_desks() -> List[Desk]:
    return [
        Desk("desk_a", 0.3, 4.2, 2.3, 5.0),
        Desk("desk_b", 2.8, 4.2, 4.8, 5.0),
        Desk("desk_c", 5.2, 4.2, 6.8, 5.0),
        Desk("desk_d", 0.3, 0.0, 2.3, 0.8),
        Desk("desk_e", 4.6, 0.0, 6.8, 0.8),
    ]


# Free spots (x, y) where the demo and the evaluation move objects to.
MOVE_SPOTS = {
    "blue_mug": (5.0, 0.65),
    "red_mug": (1.2, 0.65),
    "green_tumbler": (6.0, 0.62),
    "yellow_book": (2.0, 4.35),
}


def _unit(v: np.ndarray) -> np.ndarray:
    n = float(np.linalg.norm(v))
    return v / n if n > 0 else v


def tokenize(text: str) -> List[str]:
    return re.findall(r"[a-z]+", text.lower())


class EmbeddingSpace:
    """Attribute vectors, modality offsets, and per-object unique vectors."""

    def __init__(self, seed: int = 1234, unique_weight: float = 0.5, gap: float = 0.8):
        rng = np.random.default_rng(seed)
        self.attr: Dict[str, np.ndarray] = {a: _unit(rng.standard_normal(EMB_DIM)) for a in ATTRIBUTES}
        self.g_img = _unit(rng.standard_normal(EMB_DIM))
        self.g_txt = _unit(rng.standard_normal(EMB_DIM))
        self._unique_rng_seed = seed + 1
        self.unique_weight = unique_weight
        self.gap = gap
        self._unique: Dict[str, np.ndarray] = {}

    def _unique_vec(self, name: str) -> np.ndarray:
        if name not in self._unique:
            # deterministic per name, independent of the order objects are asked for
            h = sum((i + 1) * ord(c) for i, c in enumerate(name))
            rng = np.random.default_rng(self._unique_rng_seed * 100003 + h)
            self._unique[name] = _unit(rng.standard_normal(EMB_DIM))
        return self._unique[name]

    def concept(self, obj: SimObject) -> np.ndarray:
        v = sum(self.attr[a] for a in obj.attrs)
        v = _unit(v) + self.unique_weight * self._unique_vec(obj.name)
        return _unit(v)

    def image_embedding(self, obj: SimObject, rng: Optional[np.random.Generator] = None,
                        noise: float = 0.25) -> np.ndarray:
        v = self.concept(obj) + self.gap * self.g_img
        if rng is not None and noise > 0:
            v = v + rng.standard_normal(EMB_DIM) * (noise / math.sqrt(EMB_DIM))
        return _unit(v).astype(np.float32)

    def clutter_embedding(self, rng: np.random.Generator) -> np.ndarray:
        """Image embedding of a false positive (no known object)."""
        v = _unit(rng.standard_normal(EMB_DIM)) + self.gap * self.g_img
        return _unit(v).astype(np.float32)

    def text_embedding(self, text: str) -> np.ndarray:
        words = tokenize(text)
        v = np.zeros(EMB_DIM)
        weight = 1.0
        for w in words:
            if w in CONTEXT_WORDS:
                weight = CONTEXT_WEIGHT
                continue
            a = SYNONYMS.get(w)
            if a is not None:
                v = v + weight * self.attr[a]
        if not np.any(v):
            # nothing recognised: a vague text embedding
            v = self._unique_vec("text:" + text)
        v = _unit(v) + self.gap * self.g_txt
        return _unit(v).astype(np.float32)


class SimEmbedder:
    """Implements objmem.types.Embedder for the toy world (text side; images are by object)."""

    def __init__(self, space: EmbeddingSpace):
        self.space = space

    def embed_text(self, text: str) -> np.ndarray:
        return self.space.text_embedding(text)

    def embed_images(self, images: List[np.ndarray]) -> np.ndarray:
        # The toy world has no pixels; images are hashed to a stable random embedding.
        out = []
        for img in images:
            rng = np.random.default_rng(int(np.asarray(img).sum()) % (2 ** 32))
            out.append(self.space.clutter_embedding(rng))
        return np.stack(out) if out else np.zeros((0, EMB_DIM), dtype=np.float32)


class ToyWorld:
    """A 7 m x 5 m room with five desks and ten objects.

    `t` is the sim clock (unix seconds). `robot` is the current robot pose.
    """

    def __init__(self, seed: int = 0, objects: Optional[Sequence[SimObject]] = None,
                 desks: Optional[Sequence[Desk]] = None, width: float = 7.0, height: float = 5.0):
        self.seed = seed
        self.width = width
        self.height = height
        self.desks: List[Desk] = list(desks) if desks is not None else default_desks()
        objs = list(objects) if objects is not None else default_objects()
        self.objects: Dict[str, SimObject] = {o.name: copy.deepcopy(o) for o in objs}
        self.space = EmbeddingSpace()
        self.t = T0
        self.robot = Pose2D(3.5, 2.5, 0.0)
        self.trail: List[Tuple[float, float]] = []
        self.moves: List[Tuple[float, str, Tuple[float, float], Tuple[float, float]]] = []

    # ---------------------------------------------------------- objects
    def object(self, name: str) -> SimObject:
        return self.objects[name]

    def truth(self) -> Dict[str, Tuple[float, float]]:
        return {n: (o.x, o.y) for n, o in self.objects.items()}

    def move(self, name: str, x: float, y: float) -> None:
        """Move an object (e.g. the user picks up the mug and puts it elsewhere)."""
        o = self.objects[name]
        self.moves.append((self.t, name, (o.x, o.y), (x, y)))
        o.x, o.y = float(x), float(y)

    def remove(self, name: str) -> None:
        del self.objects[name]

    # ---------------------------------------------------------- geometry
    def is_free(self, x: float, y: float, radius: float = 0.18) -> bool:
        """True when a robot of this radius fits at (x, y)."""
        if not (radius <= x <= self.width - radius and radius <= y <= self.height - radius):
            return False
        return not any(d.contains(x, y, margin=radius) for d in self.desks)

    def set_robot(self, pose: Pose2D) -> None:
        self.robot = Pose2D(pose.x, pose.y, pose.yaw)
        self.trail.append((pose.x, pose.y))

    def advance(self, dt: float) -> None:
        self.t += float(dt)

    def clock(self) -> float:
        return self.t

    def occupancy(self, resolution: float = 0.05):
        """The room as an objmem.viz.OccupancyGrid (walls and desks occupied)."""
        from objmem.viz import OccupancyGrid
        margin = 0.25
        w = int(round((self.width + 2 * margin) / resolution))
        h = int(round((self.height + 2 * margin) / resolution))
        grid = np.zeros((h, w), dtype=np.int8)  # row 0 = lowest y
        ys = -margin + (np.arange(h) + 0.5) * resolution
        xs = -margin + (np.arange(w) + 0.5) * resolution
        X, Y = np.meshgrid(xs, ys)
        outside = (X < 0) | (X > self.width) | (Y < 0) | (Y > self.height)
        wall = outside & (X > -0.1) & (X < self.width + 0.1) & (Y > -0.1) & (Y < self.height + 0.1)
        grid[outside] = -1
        grid[wall] = 100
        for d in self.desks:
            grid[(X >= d.x0) & (X <= d.x1) & (Y >= d.y0) & (Y <= d.y1)] = 100
        return OccupancyGrid(grid=grid, resolution=resolution, origin=(-margin, -margin))


def patrol_path(world: ToyWorld, part: str = "full") -> List[Pose2D]:
    """Stops along the aisle, each looking at the desks on one side.

    part: "full" (both sides, both ways), "north" (desks along the top wall),
    "south" (desks along the bottom wall), "east" (right half of the room only).
    """
    y_mid = world.height / 2.0
    xs = [0.8 + 0.75 * i for i in range(8)]  # 0.8 .. 6.05
    north: List[Pose2D] = []
    south: List[Pose2D] = []
    for x in xs:
        for dyaw in (-0.35, 0.35):
            north.append(Pose2D(x, y_mid + 0.3, math.pi / 2 + dyaw))
    for x in reversed(xs):
        for dyaw in (0.35, -0.35):
            south.append(Pose2D(x, y_mid - 0.3, -math.pi / 2 + dyaw))
    if part == "north":
        return north
    if part == "south":
        return south
    if part == "east":
        return [p for p in north + south if p.x >= world.width / 2.0]
    return north + south
