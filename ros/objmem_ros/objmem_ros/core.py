"""ROS-free logic of the objmem nodes, unit-tested without rclpy.

- `ObserverCore`: one observer step (detections + pose -> geometry.observe ->
  memory.update_frame), rate limiting, "only while stopped", periodic saving.
- `SharedMemory`: one memory object shared by the observer, finder, and mapview
  in one process, with a lock around every call.
- `StatusNavigator` / `StatusVerifier`: wrap the navigator and verifier that
  `search.find` uses so each step is published on /objmem/status.
- Status strings: every line published on /objmem/status comes from `status_*`.
"""
import math
import os
import threading
import time

import numpy as np

from objmem.types import Pose2D  # noqa: F401  (re-exported for callers)

from objmem_ros import compat


# ---------------------------------------------------------------- status strings
def _f(v):
    return "{:.2f}".format(v)


def status_query(text):
    return "query: {}".format(text)


def status_busy(text):
    return "busy: still searching, ignored query: {}".format(text)


def status_candidates(cands):
    if not cands:
        return "candidates: none"
    parts = ["id={} sim={} p={} score={}".format(c.item.id, _f(c.sim), _f(c.item.p), _f(c.score))
             for c in cands]
    return "candidates: " + "; ".join(parts)


def status_goal_sent(n, pose):
    return "goal_sent: #{} x={} y={} yaw={}".format(n, _f(pose.x), _f(pose.y), _f(pose.yaw))


def status_goal_result(n, reached):
    return "goal_{}: #{}".format("reached" if reached else "failed", n)


def status_recheck(found, prob):
    return "recheck: {} prob={}".format("found" if found else "not_found", _f(prob))


def status_result(result):
    if result.status == "found" and result.item is not None:
        it = result.item
        label = " label={}".format(it.label) if it.label else ""
        return "result: found id={} x={} y={} p={}{}".format(it.id, _f(it.mu[0]), _f(it.mu[1]), _f(it.p), label)
    tried = ", ".join("{}:{}".format(i, o) for i, o in result.tried)
    return "result: {} tried=[{}]".format(result.status, tried)


def status_error(msg):
    return "error: {}".format(msg)


def status_observe(n_det, n_obs, n_items):
    return "observe: detections={} observations={} memories={}".format(n_det, n_obs, n_items)


# ---------------------------------------------------------------- shared memory
class SharedMemory(object):
    """Lock-protected proxy around one MemoryAPI object.

    Every method takes the lock for the duration of that call only, so a long
    search (which calls query, then drives, then mark_*) never blocks the
    observer while the robot drives.
    """

    def __init__(self, memory):
        self._mem = memory
        self.lock = threading.RLock()
        self.version = 0  # bumped on every change; mapview uses it

    @property
    def items(self):
        with self.lock:
            return list(self._mem.items)

    def update_frame(self, observations, pose, in_view, t):
        with self.lock:
            self._mem.update_frame(observations, pose, in_view, t)
            self.version += 1

    def query(self, text_embedding, t, k=None):
        with self.lock:
            return self._mem.query(text_embedding, t, k)

    def mark_found(self, item_id, t):
        with self.lock:
            self._mem.mark_found(item_id, t)
            self.version += 1

    def mark_not_found(self, item_id, t):
        with self.lock:
            self._mem.mark_not_found(item_id, t)
            self.version += 1

    def save(self, path):
        with self.lock:
            save_memory(self._mem, path)

    def replace(self, memory):
        with self.lock:
            self._mem = memory
            self.version += 1


def npz_path(path):
    """np.savez appends .npz; keep the configured name predictable."""
    return path if path.endswith(".npz") else path + ".npz"


def save_memory(memory, path):
    """Atomic save: write <name>.tmp.npz, then rename over the target."""
    path = npz_path(path)
    d = os.path.dirname(os.path.abspath(path))
    if d and not os.path.isdir(d):
        os.makedirs(d)
    tmp = path[:-4] + ".tmp.npz"
    memory.save(tmp)
    os.replace(tmp, path)


def load_or_create_memory(path, params, memory_cls=None):
    """Load the memory file when it exists, else an empty memory."""
    cls = memory_cls or compat.memory_class()
    if path:
        p = npz_path(path)
        if os.path.exists(p):
            return cls.load(p, params), True
    return cls(params), False


class FileWatcher(object):
    """File hand-off for standalone nodes: reload when the memory file changes on disk."""

    def __init__(self, path):
        self.path = npz_path(path) if path else ""
        self._mtime = self._stat()

    def _stat(self):
        try:
            return os.path.getmtime(self.path) if self.path else None
        except OSError:
            return None

    def changed(self):
        m = self._stat()
        if m is not None and m != self._mtime:
            self._mtime = m
            return True
        return False


# ---------------------------------------------------------------- observer
class RateLimiter(object):
    def __init__(self, rate_hz):
        self.period = 1.0 / rate_hz if rate_hz > 0 else 0.0
        self._last = None

    def ready(self, t):
        if self._last is None or t - self._last >= self.period:
            self._last = t
            return True
        return False


class MotionGate(object):
    """Tells whether the robot has been still for `settle_s` seconds.

    Fed with poses (from TF). A sample counts as motion when it is more than
    `lin_eps` meters or `ang_eps` radians from the previous sample.
    """

    def __init__(self, lin_eps=0.02, ang_eps=0.03, settle_s=0.5, turn_rate=0.08, turn_hold_s=0.5):
        self.lin_eps, self.ang_eps, self.settle_s = lin_eps, ang_eps, settle_s
        self.turn_rate, self.turn_hold_s = turn_rate, turn_hold_s
        self._prev = None
        self._t_prev = None
        self._t_moved = None
        self._t_turned = None

    def update(self, pose, t):
        if self._prev is None:
            self._t_moved = t
        else:
            dl = math.hypot(pose.x - self._prev.x, pose.y - self._prev.y)
            da = abs(math.atan2(math.sin(pose.yaw - self._prev.yaw), math.cos(pose.yaw - self._prev.yaw)))
            if dl > self.lin_eps or da > self.ang_eps:
                self._t_moved = t
            dt = t - self._t_prev if self._t_prev is not None else 0.0
            if dt > 1e-3 and da / dt > self.turn_rate:
                self._t_turned = t
        self._prev = pose
        self._t_prev = t
        # A sample that counts as motion keeps its pose as the reference; a small step is
        # compared with the next one instead (slow drift still adds up to "moved").

    def stopped(self, t):
        return self._t_moved is not None and t - self._t_moved >= self.settle_s

    def turning(self, t):
        """The heading changed faster than turn_rate (rad/s) within the last turn_hold_s."""
        return self._t_turned is not None and t - self._t_turned < self.turn_hold_s


class ObserverCore(object):
    """The per-frame observer step without ROS.

    The node calls `tick(pose, t)` often (every TF update or timer); `tick`
    decides whether to run a step now and, if so, calls `get_detections()`
    (the worker request), places the detections on the map, and updates the
    memory.
    """

    def __init__(self, memory, params, rate_hz=1.0, only_when_stopped=True, save_path="",
                 save_period_s=30.0, settle_s=0.5, observe=None, make_in_view=None,
                 skip_while_turning=False):
        self.memory = memory
        self.params = params
        self.limiter = RateLimiter(rate_hz)
        self.only_when_stopped = only_when_stopped
        # Observing while driving straight is fine (0.12 m/s: the pose moves 1 to 2 cm between
        # the TF lookup and the camera frame); while turning the picture smears and the same
        # delay is a few degrees of bearing, so those frames are skipped.
        self.skip_while_turning = skip_while_turning
        self.gate = MotionGate(settle_s=settle_s)
        self.save_path = save_path
        self.save_period_s = save_period_s
        self._last_save = None
        self._dirty = False
        self.observe = observe or compat.observe_fn()
        self.in_view = (make_in_view or compat.make_in_view_fn())(params)
        self.paused = False  # set while the finder drives, if configured
        self.n_steps = 0
        self.last_status = ""

    def feed_pose(self, pose, t):
        self.gate.update(pose, t)

    def should_step(self, t):
        if self.paused:
            return False
        if self.only_when_stopped and not self.gate.stopped(t):
            return False
        if self.skip_while_turning and self.gate.turning(t):
            return False
        return self.limiter.ready(t)

    def step(self, detections, pose, t):
        """detections (List[Detection]) seen from `pose` at time t -> memory update. Returns status."""
        obs = []
        for det in detections:
            o = self.observe(det, pose, self.params, t)
            if o is not None:
                obs.append(o)
        self.memory.update_frame(obs, pose, self.in_view, t)
        self._dirty = True
        self.n_steps += 1
        self.last_status = status_observe(len(detections), len(obs), len(self.memory.items))
        return self.last_status

    def tick(self, pose, t, get_detections):
        """Feed the pose and run a step when due. Returns the status string, or None if skipped."""
        self.feed_pose(pose, t)
        if not self.should_step(t):
            return None
        dets = get_detections()
        if dets is None:
            return None
        return self.step(dets, pose, t)

    def mark_dirty(self):
        """Something else (the finder) changed the memory; include it in the next periodic save."""
        self._dirty = True

    def maybe_save(self, t, force=False):
        """Save when the period elapsed and something changed (or force). Returns True if saved."""
        if not self.save_path:
            return False
        if self._last_save is None:
            self._last_save = t
        due = t - self._last_save >= self.save_period_s
        if force or (due and self._dirty):
            self.memory.save(self.save_path)
            self._last_save = t
            self._dirty = False
            return True
        return False


def fill_depth(detections, depth, median_depth=None, scale_xy=(1.0, 1.0)):
    """image_source:=ros: the worker returns depth_m=None; look it up in our depth image.

    `scale_xy` maps color pixels to depth pixels when the two sizes differ.
    """
    if depth is None:
        return detections
    md = median_depth or compat.median_depth_fn()
    sx, sy = scale_xy
    for det in detections:
        if det.depth_m is None:
            l, t, r, b = det.box
            box = (int(l * sx), int(t * sy), int(r * sx), int(b * sy))
            det.depth_m = md(depth, box)
    return detections


def depth_from_image_msg(encoding, height, width, step, data, is_bigendian=False):
    """sensor_msgs/Image fields -> (H, W) float32 meters. 16UC1 is millimeters (RealSense)."""
    buf = bytes(data)
    if encoding in ("16UC1", "mono16"):
        dt = np.dtype(">u2" if is_bigendian else "<u2")
        arr = np.frombuffer(buf, dtype=dt).reshape(height, step // 2)[:, :width]
        return arr.astype(np.float32) * 0.001
    if encoding == "32FC1":
        dt = np.dtype(">f4" if is_bigendian else "<f4")
        arr = np.frombuffer(buf, dtype=dt).reshape(height, step // 4)[:, :width].astype(np.float32)
        arr[~np.isfinite(arr)] = 0.0
        return arr
    raise ValueError("unsupported depth encoding: {}".format(encoding))


def params_with_camera_info(params, k, width, height):
    """Copy of params with intrinsics from a CameraInfo K matrix (row-major 3x3)."""
    import copy
    p = copy.copy(params)
    if len(k) >= 6 and k[0] > 0:
        p.fx, p.cx, p.fy, p.cy = float(k[0]), float(k[2]), float(k[4]), float(k[5])
        p.img_w, p.img_h = int(width), int(height)
        p.hfov = 2.0 * math.atan2(p.img_w / 2.0, p.fx)
    return p


def yaw_from_quaternion(x, y, z, w):
    return math.atan2(2.0 * (w * z + x * y), 1.0 - 2.0 * (y * y + z * z))


def quaternion_from_yaw(yaw):
    """(x, y, z, w)"""
    return 0.0, 0.0, math.sin(yaw / 2.0), math.cos(yaw / 2.0)


# ---------------------------------------------------------------- finder
class StatusNavigator(object):
    """Navigator wrapper that reports each goal on the status topic."""

    def __init__(self, navigator, emit):
        self.navigator, self.emit, self.n = navigator, emit, 0

    def go_to(self, pose):
        self.n += 1
        self.emit(status_goal_sent(self.n, pose))
        ok = bool(self.navigator.go_to(pose))
        self.emit(status_goal_result(self.n, ok))
        return ok


class StatusVerifier(object):
    def __init__(self, verifier, emit):
        self.verifier, self.emit = verifier, emit

    def check(self, text):
        found, prob = self.verifier.check(text)
        self.emit(status_recheck(found, prob))
        return found, prob


class StatusMemory(object):
    """Memory wrapper that reports the candidate list the search will visit."""

    def __init__(self, memory, emit):
        self._mem, self.emit = memory, emit

    def __getattr__(self, name):
        return getattr(self._mem, name)

    @property
    def items(self):
        return self._mem.items

    def query(self, text_embedding, t, k=None):
        cands = self._mem.query(text_embedding, t, k)
        self.emit(status_candidates(cands))
        return cands


class FinderCore(object):
    """Runs one search at a time and reports progress through `emit`."""

    def __init__(self, memory, embedder, navigator, verifier, params, emit, find=None,
                 clock=time.time, on_change=None):
        self.memory, self.embedder, self.navigator, self.verifier = memory, embedder, navigator, verifier
        self.params, self.emit, self.clock = params, emit, clock
        self.find = find or compat.find_fn()
        self.on_change = on_change
        self._busy = threading.Lock()

    @property
    def busy(self):
        return self._busy.locked()

    def run(self, text):
        """Blocking search. Returns the SearchResult, or None if busy or failed."""
        text = text.strip()
        if not text:
            return None
        if not self._busy.acquire(False):
            self.emit(status_busy(text))
            return None
        try:
            self.emit(status_query(text))
            result = self.find(text, StatusMemory(self.memory, self.emit), self.embedder,
                               StatusNavigator(self.navigator, self.emit),
                               StatusVerifier(self.verifier, self.emit), self.params, clock=self.clock)
            self.emit(status_result(result))
            if self.on_change is not None:
                self.on_change()
            return result
        except Exception as exc:  # report, keep the node alive
            self.emit(status_error("{}: {}".format(type(exc).__name__, exc)))
            return None
        finally:
            self._busy.release()


# ---------------------------------------------------------------- mapview
def items_json(items):
    out = []
    for it in items:
        out.append({"id": int(it.id), "label": it.label, "x": float(it.mu[0]), "y": float(it.mu[1]),
                    "cov": np.asarray(it.cov, dtype=float).tolist(), "p": float(it.p),
                    "t_last": float(it.t_last), "n_obs": int(it.n_obs)})
    return out


MAP_PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><title>objmem map</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>body{{font-family:sans-serif;background:#fff;color:#222;margin:16px}}
img{{max-width:100%;border:1px solid #ccc}}pre{{white-space:pre-wrap}}</style></head>
<body><h3>objmem map</h3><img id="m" src="/map.png" alt="map"><pre id="s"></pre>
<script>
function r(){{document.getElementById('m').src='/map.png?t='+Date.now();
fetch('/items.json').then(x=>x.json()).then(j=>{{document.getElementById('s').textContent=
j.status+'\\n'+j.items.map(i=>'#'+i.id+' '+(i.label||'')+' ('+i.x.toFixed(2)+', '+i.y.toFixed(2)+') p='+i.p.toFixed(2)).join('\\n');}}).catch(()=>{{}});}}
setInterval(r,{refresh_ms});r();
</script></body></html>
"""


def ellipse_axes(cov):
    """(major std, minor std, angle of the major axis) of a 2x2 covariance."""
    w, v = np.linalg.eigh(np.asarray(cov, dtype=float))
    w = np.clip(w, 0.0, None)
    return float(math.sqrt(w[1])), float(math.sqrt(w[0])), float(math.atan2(v[1, 1], v[0, 1]))
