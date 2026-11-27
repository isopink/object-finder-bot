"""Shared data types and interfaces for objmem.

Every module codes against the names in this file. Do not change it in a lane
branch; report the change you need instead. Python 3.8 compatible.
"""
from dataclasses import dataclass, field, fields
from typing import Callable, List, Optional, Protocol, Tuple

import numpy as np

Box = Tuple[int, int, int, int]  # (left, top, right, bottom) in pixels

DEFAULT_BACKGROUND_PROMPTS = [
    "a photo of a wall", "a photo of the floor", "a photo of a ceiling", "a photo of a desk",
    "a photo of a chair", "a photo of a person", "a photo of a computer monitor",
    "a photo of a keyboard", "a blurry photo of a room",
]


# ---------------------------------------------------------------- data types
@dataclass
class Pose2D:
    """Robot pose or goal in the map frame."""
    x: float
    y: float
    yaw: float  # rad


@dataclass
class Frame:
    """One camera frame."""
    color: np.ndarray            # (H, W, 3) uint8 RGB
    depth: Optional[np.ndarray]  # (H, W) float32 meters, aligned to color, 0 = invalid; None without depth
    t: float                     # unix seconds


@dataclass
class RawBox:
    """Detector output before embedding."""
    box: Box
    label: str
    conf: float


@dataclass
class Detection:
    """Vision worker output: a box with its CLIP embedding."""
    box: Box
    label: str
    conf: float
    embedding: np.ndarray            # (512,) float32, L2-normalized
    depth_m: Optional[float] = None  # median depth near the box center; None without depth


@dataclass
class Observation:
    """A detection placed on the map (output of geometry.observe)."""
    embedding: np.ndarray            # (512,) L2-normalized
    mu: np.ndarray                   # (2,) map position (x, y)
    cov: np.ndarray                  # (2, 2) position covariance
    t: float                         # unix seconds
    view_pose: Pose2D                # robot pose when the object was seen
    label: Optional[str] = None
    bearing: Optional[float] = None  # map-frame angle robot -> object (rad); set only in nodepth mode


@dataclass
class MemoryItem:
    """One remembered object (proposal section 4)."""
    id: int
    mu: np.ndarray         # (2,)
    cov: np.ndarray        # (2, 2)
    embedding: np.ndarray  # (512,) L2-normalized
    p: float               # existence confidence in [0, 1]
    t_last: float          # last time the object was detected
    n_obs: int
    view_pose: Pose2D      # robot pose at the latest detection
    label: Optional[str] = None


@dataclass
class Candidate:
    """A search result: score = softmax(sim / T) * p (proposal 4.4)."""
    item: MemoryItem
    sim: float
    score: float


@dataclass
class SearchResult:
    status: str                   # "found" | "not_found" | "nav_failed" | "empty"
    item: Optional[MemoryItem]    # the item that was found, else None
    tried: List[Tuple[int, str]]  # (item id, "found" | "not_found" | "nav_failed") in visit order


# ---------------------------------------------------------------- parameters
@dataclass
class Params:
    """All tunable values. config/default.yaml holds the same keys (flat)."""
    # Existence confidence (proposal 4.3)
    d: float = 0.8              # P(detect | present)
    f: float = 0.1              # P(detect | absent)
    tau: float = 600.0          # time-decay constant (s)
    p_init: float = 0.7         # confidence of a new memory
    # Same-object test (proposal 4.2)
    maha_thresh: float = 3.0    # Mahalanobis distance gate
    cos_thresh: float = 0.8     # CLIP image-image cosine gate
    cos_thresh_same_label: float = 0.0  # cosine gate when observation and memory have the same label; 0 = use cos_thresh
    merge_dist: float = 0.0     # merge two memories of the same object closer than this (m); 0 = never merge
    pos_std_min: float = 0.0    # smallest position std kept after fusion (m); 0 = no floor
    # Search (proposal 4.4)
    T: float = 0.05             # softmax temperature over query-memory similarity
    top_k: int = 3
    found_thresh: float = 0.5   # re-check probability that counts as found
    standoff: float = 0.6       # stop this far from the object (m)
    pos_cov_max: float = 0.25   # largest position-covariance eigenvalue (m^2) above which the goal is view_pose
    # Camera
    camera_mode: str = "depth"  # "depth" (RealSense) | "nodepth" (C920)
    img_w: int = 640
    img_h: int = 480
    fx: float = 615.0
    fy: float = 615.0
    cx: float = 320.0
    cy: float = 240.0
    hfov: float = 0.96          # horizontal field of view (rad); 2 atan(img_w / 2 fx) for the defaults
    depth_min: float = 0.3      # usable depth range (m); depth_max is also the max range in nodepth mode
    depth_max: float = 4.0
    # Camera mount T_base<-cam: position (m) and angles (rad) of the camera in base_link
    cam_x: float = 0.05
    cam_y: float = 0.0
    cam_z: float = 0.6
    cam_yaw: float = 0.0
    cam_pitch: float = 0.0      # positive = tilted down
    # Observation noise
    sigma_range_a: float = 0.02      # range std = a + b * range^2 (m), depth mode
    sigma_range_b: float = 0.01
    sigma_bearing: float = 0.03      # bearing std (rad), both modes
    nominal_range: float = 2.0       # assumed range of a first sighting, nodepth mode (m)
    sigma_range_nodepth: float = 1.5 # range std along the ray, nodepth mode (m)
    # Vision
    crop_pad: float = 0.1
    clip_logit_scale: float = 100.0
    background_prompts: List[str] = field(default_factory=lambda: list(DEFAULT_BACKGROUND_PROMPTS))
    # Processes
    worker_url: str = "http://127.0.0.1:8600"
    mapview_port: int = 8555
    search_log: str = ""        # JSON-lines log of every query (scripts/evaluate.py reads it); "" = no log
    # Speech queries (extension)
    whisper_model: str = "base.en"
    mic_device: str = ""        # ALSA device for arecord, e.g. plughw:2,0; "" = default

    @classmethod
    def load(cls, path: Optional[str] = None) -> "Params":
        """Defaults overridden by a flat YAML mapping. Unknown keys raise ValueError."""
        params = cls()
        if path is None:
            return params
        import yaml
        with open(path, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
        names = {f.name for f in fields(cls)}
        unknown = sorted(set(data) - names)
        if unknown:
            raise ValueError("Unknown config keys: {}".format(", ".join(unknown)))
        for key, value in data.items():
            setattr(params, key, value)
        return params


# ---------------------------------------------------------------- interfaces
InView = Callable[[np.ndarray, Pose2D], bool]  # (mu, robot pose) -> is that map point visible now


class Embedder(Protocol):
    def embed_images(self, images: List[np.ndarray]) -> np.ndarray:
        """List of RGB crops -> (N, 512) L2-normalized float32."""
        ...

    def embed_text(self, text: str) -> np.ndarray:
        """Sentence -> (512,) L2-normalized float32."""
        ...


class Detector(Protocol):
    def detect(self, color: np.ndarray) -> List[RawBox]:
        ...


class FrameSource(Protocol):
    def read(self) -> Optional[Frame]:
        """Latest frame, or None when no frame is available."""
        ...


class Navigator(Protocol):
    def go_to(self, pose: Pose2D) -> bool:
        """Drive to the pose. Blocks. True when the goal was reached."""
        ...


class Verifier(Protocol):
    def check(self, text: str) -> Tuple[bool, float]:
        """Re-check the live view for the query. Returns (found, probability)."""
        ...


class SpeechToText(Protocol):
    def listen(self) -> str:
        """Record one utterance and return the recognized English text."""
        ...


class MemoryAPI(Protocol):
    """What objmem.memory.ObjectMemory provides. ObjectMemory(params) builds an empty memory;
    ObjectMemory.load(path, params) is a classmethod that restores a saved one."""

    @property
    def items(self) -> List[MemoryItem]:
        ...

    def update_frame(self, observations: List[Observation], pose: Pose2D, in_view: InView, t: float) -> None:
        """Matched memories: fuse position and raise p. Memories in view but unmatched: lower p.
        Unmatched observations: new memories. Position fusion is a Kalman update when
        observation.bearing is None, else an EKF update with a bearing measurement."""
        ...

    def query(self, text_embedding: np.ndarray, t: float, k: Optional[int] = None) -> List[Candidate]:
        """Top-k candidates by softmax(sim / T) * p, with p decayed to time t. k defaults to params.top_k."""
        ...

    def mark_found(self, item_id: int, t: float) -> None:
        ...

    def mark_not_found(self, item_id: int, t: float) -> None:
        ...

    def save(self, path: str) -> None:
        ...
