"""rclpy nodes: observer, finder, mapview, and all three in one process.

Same source for Foxy and Humble: only APIs present in both are used.

`ros2 run objmem_ros objmem` (what the launch file starts) runs the three nodes
in one process sharing one memory object. The standalone executables
(`observer`, `finder`, `mapview`) share the memory through the memory file
instead: the observer saves it every `save_period_s`, and the finder and the
mapview reload it when it changes on disk.
"""
import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn

import rclpy
from rclpy.action import ActionClient
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy

from std_msgs.msg import String

from objmem.types import Params, Pose2D

from objmem_ros import compat, core


def _descriptor():
    from rcl_interfaces.msg import ParameterDescriptor
    try:
        return ParameterDescriptor(dynamic_typing=True)  # Humble; Foxy has no such field
    except (TypeError, AttributeError, AssertionError):
        return ParameterDescriptor()


def _coerce(value, default):
    """Convert a parameter value (often a string from launch) to the type of `default`."""
    if value is None:
        return default
    if isinstance(default, bool):
        if isinstance(value, str):
            return value.strip().lower() in ("1", "true", "yes", "on")
        return bool(value)
    if isinstance(default, int):
        return int(float(value))
    if isinstance(default, float):
        return float(value)
    if isinstance(default, str):
        return str(value)
    return value


def _declare(node, name, default):
    """Declare with dynamic typing (strings from launch files are fine) and return a typed value."""
    if not node.has_parameter(name):
        node.declare_parameter(name, default, _descriptor())
    return _coerce(node.get_parameter(name).value, default)


class Shared(object):
    """What the three nodes share inside one process."""

    def __init__(self, logger, config, memory_file):
        self.params = Params.load(config) if config else Params()
        mem, loaded = core.load_or_create_memory(memory_file, self.params)
        self.memory = core.SharedMemory(mem)
        self.memory_file = memory_file
        self.robot_pose = None  # latest Pose2D from TF
        self.navigating = False
        logger.info("config={} memory_file={} ({} memories{})".format(
            config or "<defaults>", memory_file or "<none>", len(self.memory.items),
            ", loaded" if loaded else ", new"))
        missing = compat.probe_all()
        if missing:
            logger.warn("missing: {} (mapview draws a plain map without labels; install python3-pil)".format(", ".join(missing)))


def _common_params(node):
    config = _declare(node, "config", "")
    memory_file = _declare(node, "memory_file", "")
    return config, memory_file


def _status_publisher(node):
    pub = node.create_publisher(String, "/objmem/status", 10)

    def emit(text):
        msg = String()
        msg.data = text
        pub.publish(msg)
        node.get_logger().info(text)
    return emit


# ---------------------------------------------------------------- TF pose
class TfPose(object):
    def __init__(self, node, map_frame="map", base_frame="base_link"):
        import tf2_ros
        self.node, self.map_frame, self.base_frame = node, map_frame, base_frame
        self.buffer = tf2_ros.Buffer()
        self.listener = tf2_ros.TransformListener(self.buffer, node)
        self._warned = 0.0

    def lookup(self):
        """Latest map -> base_link as Pose2D, or None."""
        from rclpy.time import Time
        try:
            tf = self.buffer.lookup_transform(self.map_frame, self.base_frame, Time())
        except Exception as exc:  # tf2 raises several exception types
            now = time.time()
            if now - self._warned > 10.0:
                self.node.get_logger().warn("no TF {} -> {}: {}".format(self.map_frame, self.base_frame, exc))
                self._warned = now
            return None
        tr, q = tf.transform.translation, tf.transform.rotation
        return Pose2D(float(tr.x), float(tr.y), core.yaw_from_quaternion(q.x, q.y, q.z, q.w))


# ---------------------------------------------------------------- observer
class ObserverNode(Node):
    def __init__(self, shared=None):
        super().__init__("objmem_observer")
        config, memory_file = _common_params(self)
        self.shared = shared or Shared(self.get_logger(), config, memory_file)
        p = self.shared.params
        self.image_source = _declare(self, "image_source", "worker")
        rate = float(_declare(self, "observe_rate", 1.0))
        only_stopped = bool(_declare(self, "only_when_stopped", True))
        skip_turning = bool(_declare(self, "skip_while_turning", False))
        pause_nav = bool(_declare(self, "pause_while_navigating", True))
        save_period = float(_declare(self, "save_period_s", 30.0))
        settle = float(_declare(self, "settle_s", 0.5))
        self.worker_url = _declare(self, "worker_url", p.worker_url)
        self.timeout = float(_declare(self, "worker_timeout", 10.0))
        map_frame = _declare(self, "map_frame", "map")
        base_frame = _declare(self, "base_frame", "base_link")
        self.pause_nav = pause_nav

        self.core = core.ObserverCore(self.shared.memory, p, rate_hz=rate, only_when_stopped=only_stopped,
                                      save_path=self.shared.memory_file, save_period_s=save_period,
                                      settle_s=settle, skip_while_turning=skip_turning)
        self.tf = TfPose(self, map_frame, base_frame)
        self._color_jpeg = None
        self._depth = None
        self._depth_shape = None
        self._color_shape = None
        self._caminfo_seen = False
        self._lock = threading.Lock()
        if self.image_source == "ros":
            self._subscribe_ros_images()
        elif self.image_source != "worker":
            raise ValueError("image_source must be 'worker' or 'ros', got {!r}".format(self.image_source))
        self.emit = _status_publisher(self)
        self._busy = False
        self.create_timer(0.1, self._on_timer)
        self.get_logger().info("observer: image_source={} rate={} Hz only_when_stopped={} skip_while_turning={} worker={}".format(
            self.image_source, rate, only_stopped, skip_turning, self.worker_url))

    def _subscribe_ros_images(self):
        from sensor_msgs.msg import CameraInfo, CompressedImage, Image
        color = _declare(self, "color_topic", "/camera/color/image_raw/compressed")
        depth = _declare(self, "depth_topic", "/camera/aligned_depth_to_color/image_raw")
        info = _declare(self, "camera_info_topic", "/camera/color/camera_info")
        qos = QoSProfile(depth=1, reliability=ReliabilityPolicy.BEST_EFFORT, history=HistoryPolicy.KEEP_LAST)
        self.create_subscription(CompressedImage, color, self._on_color, qos)
        if self.shared.params.camera_mode == "depth":
            self.create_subscription(Image, depth, self._on_depth, qos)
        self.create_subscription(CameraInfo, info, self._on_info, qos)
        self.get_logger().info("ros images: color={} depth={} info={}".format(color, depth, info))

    def _on_color(self, msg):
        if "png" in msg.format.lower() and not getattr(self, "_png_warned", False):
            self.get_logger().warn("compressed color is PNG ({}); the worker expects JPEG".format(msg.format))
            self._png_warned = True
        with self._lock:
            self._color_jpeg = bytes(msg.data)

    def _on_depth(self, msg):
        try:
            d = core.depth_from_image_msg(msg.encoding, msg.height, msg.width, msg.step, msg.data,
                                          bool(msg.is_bigendian))
        except ValueError as exc:
            self.get_logger().error(str(exc))
            return
        with self._lock:
            self._depth = d

    def _on_info(self, msg):
        if self._caminfo_seen:
            return
        k = list(msg.k) if hasattr(msg, "k") else list(msg.K)
        self.core.params = core.params_with_camera_info(self.core.params, k, msg.width, msg.height)
        self._color_shape = (msg.height, msg.width)
        self._caminfo_seen = True
        p = self.core.params
        self.get_logger().info("camera_info: fx={:.1f} fy={:.1f} cx={:.1f} cy={:.1f} {}x{}".format(
            p.fx, p.fy, p.cx, p.cy, p.img_w, p.img_h))

    def _detections(self):
        try:
            if self.image_source == "worker":
                return compat.detect_embed_jpeg(self.worker_url, None, self.timeout)
            with self._lock:
                jpeg, depth = self._color_jpeg, self._depth
            if jpeg is None:
                return None
            dets = compat.detect_embed_jpeg(self.worker_url, jpeg, self.timeout)
            if depth is not None and self.core.params.camera_mode == "depth":
                scale = (1.0, 1.0)
                if self._color_shape is not None and depth.shape[:2] != self._color_shape:
                    scale = (depth.shape[1] / float(self._color_shape[1]),
                             depth.shape[0] / float(self._color_shape[0]))
                core.fill_depth(dets, depth, scale_xy=scale)
            return dets
        except Exception as exc:
            self.get_logger().warn("worker request failed: {}".format(exc))
            return None

    def _on_timer(self):
        if self._busy:
            return
        pose = self.tf.lookup()
        if pose is None:
            return
        self.shared.robot_pose = pose
        self.core.paused = self.pause_nav and self.shared.navigating
        self._busy = True
        try:
            t = time.time()
            s = self.core.tick(pose, t, self._detections)
            if s is not None:
                self.emit(s)
            if self.core.maybe_save(t):
                self.get_logger().info("saved {}".format(core.npz_path(self.shared.memory_file)))
        finally:
            self._busy = False

    def save_now(self):
        if self.shared.memory_file:
            self.core.maybe_save(time.time(), force=True)
            print("[objmem] saved {}".format(core.npz_path(self.shared.memory_file)))


# ---------------------------------------------------------------- Nav2 navigator
class Nav2Navigator(object):
    """Blocking Navigator over the Nav2 `navigate_to_pose` action, with timeout and cancel.

    go_to() must not run on the executor thread: it waits on futures that the
    executor (spinning in another thread) completes.
    """

    def __init__(self, node, action_name="navigate_to_pose", frame="map", timeout_s=120.0,
                 server_wait_s=10.0, on_state=None):
        from nav2_msgs.action import NavigateToPose
        self.node, self.frame, self.timeout_s, self.server_wait_s = node, frame, timeout_s, server_wait_s
        self.NavigateToPose = NavigateToPose
        self.client = ActionClient(node, NavigateToPose, action_name, callback_group=ReentrantCallbackGroup())
        self.on_state = on_state or (lambda moving: None)
        self._goal = None
        self.cancel_requested = threading.Event()

    @staticmethod
    def _wait(future, timeout):
        ev = threading.Event()
        future.add_done_callback(lambda _f: ev.set())
        if future.done():
            ev.set()
        return ev.wait(timeout)

    def cancel(self):
        self.cancel_requested.set()
        g = self._goal
        if g is not None:
            g.cancel_goal_async()

    def go_to(self, pose):
        from action_msgs.msg import GoalStatus
        log = self.node.get_logger()
        if not self.client.wait_for_server(timeout_sec=self.server_wait_s):
            log.error("Nav2 action server not available")
            return False
        goal = self.NavigateToPose.Goal()
        goal.pose.header.frame_id = self.frame
        goal.pose.header.stamp = self.node.get_clock().now().to_msg()
        goal.pose.pose.position.x = float(pose.x)
        goal.pose.pose.position.y = float(pose.y)
        qx, qy, qz, qw = core.quaternion_from_yaw(pose.yaw)
        goal.pose.pose.orientation.x, goal.pose.pose.orientation.y = qx, qy
        goal.pose.pose.orientation.z, goal.pose.pose.orientation.w = qz, qw
        self.cancel_requested.clear()
        self.on_state(True)
        try:
            fut = self.client.send_goal_async(goal)
            if not self._wait(fut, self.server_wait_s) or fut.result() is None:
                log.error("goal send timed out")
                return False
            handle = fut.result()
            if not handle.accepted:
                log.warn("goal rejected")
                return False
            self._goal = handle
            res_fut = handle.get_result_async()
            if not self._wait(res_fut, self.timeout_s):
                log.warn("goal timed out after {:.0f} s; canceling".format(self.timeout_s))
                cf = handle.cancel_goal_async()
                self._wait(cf, 5.0)
                return False
            if self.cancel_requested.is_set():
                return False
            return res_fut.result().status == GoalStatus.STATUS_SUCCEEDED
        finally:
            self._goal = None
            self.on_state(False)


# ---------------------------------------------------------------- finder
class FinderNode(Node):
    def __init__(self, shared=None):
        super().__init__("objmem_finder")
        config, memory_file = _common_params(self)
        self.standalone = shared is None
        self.shared = shared or Shared(self.get_logger(), config, memory_file)
        p = self.shared.params
        self.worker_url = _declare(self, "worker_url", p.worker_url)
        nav_timeout = float(_declare(self, "nav_timeout_s", 120.0))
        action = _declare(self, "nav_action", "navigate_to_pose")
        frame = _declare(self, "map_frame", "map")
        self.search_log = _declare(self, "search_log", "")
        self.emit = _status_publisher(self)
        client = compat.vision_client(self.worker_url, timeout=float(_declare(self, "worker_timeout", 10.0)))

        def on_state(moving):
            self.shared.navigating = moving
        self.navigator = Nav2Navigator(self, action, frame, timeout_s=nav_timeout, on_state=on_state)
        self.core = core.FinderCore(self.shared.memory, compat.ClientTextEmbedder(client), self.navigator,
                                    compat.client_verifier(client), p, self.emit, find=self._find_fn(),
                                    on_change=self._after_search)
        self.watch = core.FileWatcher(self.shared.memory_file) if self.standalone else None
        self.create_subscription(String, "/query", self._on_query, 10,
                                 callback_group=ReentrantCallbackGroup())
        self.create_subscription(String, "/objmem/cancel", self._on_cancel, 10,
                                 callback_group=ReentrantCallbackGroup())
        self.get_logger().info("finder ready: worker={} action={}".format(self.worker_url, action))

    def _find_fn(self):
        find = compat.find_fn()
        if not self.search_log:
            return find
        import inspect
        try:
            accepts_log = "log_path" in inspect.signature(find).parameters
        except (TypeError, ValueError):
            accepts_log = False
        if not accepts_log:
            self.get_logger().warn("search.find takes no log_path; search_log ignored")
            return find

        def with_log(*a, **kw):
            kw["log_path"] = self.search_log
            return find(*a, **kw)
        return with_log

    def _after_search(self):
        if self.standalone and self.shared.memory_file:
            # Hand the updated confidences back to the file (the observer's next save may overwrite them).
            self.shared.memory.save(self.shared.memory_file)

    def _reload_if_changed(self):
        if self.watch is not None and self.watch.changed():
            mem, _ = core.load_or_create_memory(self.shared.memory_file, self.shared.params)
            self.shared.memory.replace(mem)
            self.get_logger().info("reloaded memory file ({} memories)".format(len(self.shared.memory.items)))

    def _on_query(self, msg):
        text = msg.data.strip()
        if not text:
            return
        if self.core.busy:
            self.emit(core.status_busy(text))
            return
        self._reload_if_changed()
        threading.Thread(target=self.core.run, args=(text,), daemon=True).start()

    def _on_cancel(self, _msg):
        self.navigator.cancel()
        self.emit("cancel: requested")


# ---------------------------------------------------------------- mapview
class _ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


class MapviewNode(Node):
    def __init__(self, shared=None):
        super().__init__("objmem_mapview")
        config, memory_file = _common_params(self)
        self.standalone = shared is None
        self.shared = shared or Shared(self.get_logger(), config, memory_file)
        self.port = int(_declare(self, "mapview_port", int(self.shared.params.mapview_port)))
        self.map_yaml = _declare(self, "map_yaml", "")
        refresh = float(_declare(self, "refresh_s", 2.0))
        # "x y" in map metres: an X with the word "start" on the map (where the robot is put
        # down before a run). Empty = none.
        self.start_mark = None
        mark = str(_declare(self, "start_mark", "")).replace(",", " ").split()
        if len(mark) >= 2:
            try:
                self.start_mark = (float(mark[0]), float(mark[1]))
            except ValueError:
                self.get_logger().warn("start_mark {!r} is not 'x y'; no start mark".format(mark))
        self.draw_map = compat.draw_map_fn()
        self.watch = core.FileWatcher(self.shared.memory_file) if self.standalone else None
        self.tf = TfPose(self) if self.standalone else None
        self.status = ""
        self.create_subscription(String, "/objmem/status", self._on_status, 10)
        self.plan, self.plan_version = [], 0
        self.trail = core.Trail()   # where the robot has been since this node started (blue line)
        try:
            from nav_msgs.msg import Path
            from rclpy.qos import QoSProfile, DurabilityPolicy, ReliabilityPolicy
            self.create_subscription(Path, "/gridnav/plan", self._on_plan, QoSProfile(
                depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL, reliability=ReliabilityPolicy.RELIABLE))
        except Exception as exc:  # noqa: BLE001 - the view works without the plan
            self.get_logger().warn("no plan drawing: {}".format(exc))
        from visualization_msgs.msg import MarkerArray
        self.markers_pub = self.create_publisher(MarkerArray, "/objmem/markers", 1)
        self.create_timer(1.0, self._on_timer)
        self._png, self._png_key = None, None
        self._png_lock = threading.Lock()
        self.server = _ThreadingHTTPServer(("0.0.0.0", self.port), self._handler())
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.page = core.MAP_PAGE.format(refresh_ms=int(refresh * 1000))
        self.get_logger().info("mapview on http://<jetson-ip>:{}/".format(self.port))

    def _on_status(self, msg):
        self.status = msg.data

    def _on_plan(self, msg):
        self.plan = [(p.pose.position.x, p.pose.position.y) for p in msg.poses]
        self.plan_version += 1

    def _robot_pose(self):
        if self.tf is not None:
            p = self.tf.lookup()
            if p is not None:
                self.shared.robot_pose = p
        return self.shared.robot_pose

    def _on_timer(self):
        if self.watch is not None and self.watch.changed():
            mem, _ = core.load_or_create_memory(self.shared.memory_file, self.shared.params)
            self.shared.memory.replace(mem)
        pose = self._robot_pose()
        if pose is not None:
            self.trail.add(pose.x, pose.y)
        self.markers_pub.publish(self._markers())

    def _markers(self):
        from visualization_msgs.msg import Marker, MarkerArray
        arr = MarkerArray()
        clear = Marker()
        clear.action = 3  # DELETEALL
        arr.markers.append(clear)
        now = self.get_clock().now().to_msg()
        for it in self.shared.memory.items:
            major, minor, ang = core.ellipse_axes(it.cov)
            qx, qy, qz, qw = core.quaternion_from_yaw(ang)
            m = Marker()
            m.header.frame_id, m.header.stamp = "map", now
            m.ns, m.id, m.type, m.action = "objmem", int(it.id) * 2, Marker.CYLINDER, Marker.ADD
            m.pose.position.x, m.pose.position.y, m.pose.position.z = float(it.mu[0]), float(it.mu[1]), 0.05
            m.pose.orientation.x, m.pose.orientation.y = qx, qy
            m.pose.orientation.z, m.pose.orientation.w = qz, qw
            m.scale.x, m.scale.y, m.scale.z = max(0.05, 4 * major), max(0.05, 4 * minor), 0.05
            m.color.r, m.color.g, m.color.b, m.color.a = float(1 - it.p), float(it.p), 0.0, 0.6
            arr.markers.append(m)
            t = Marker()
            t.header.frame_id, t.header.stamp = "map", now
            t.ns, t.id, t.type, t.action = "objmem", int(it.id) * 2 + 1, Marker.TEXT_VIEW_FACING, Marker.ADD
            t.pose.position.x, t.pose.position.y, t.pose.position.z = float(it.mu[0]), float(it.mu[1]), 0.3
            t.pose.orientation.w = 1.0
            t.scale.z = 0.12
            t.color.r = t.color.g = t.color.b = t.color.a = 1.0
            t.text = "#{} {} p={:.2f}".format(it.id, it.label or "", it.p)
            arr.markers.append(t)
        return arr

    def _occupancy(self):
        return self.map_yaml or None

    def _warn_once(self, key, text):
        warned = self.__dict__.setdefault("_warned", set())
        if key not in warned:
            warned.add(key)
            self.get_logger().warn(text)

    def _draw(self, items, pose):
        """objmem.viz.draw_map; on failure retry without the grid, then the plain drawing."""
        occ = self._occupancy()
        mark = getattr(self, "start_mark", None)
        trail = self.trail.points()         # blue line: where the robot has been
        if mark is not None and occ is not None:
            kw = {"truth": {"start": mark}}
            if self.plan:
                kw["plan"] = self.plan
            try:
                return self.draw_map(items, robot_pose=pose, occupancy=occ, path=trail, **kw)
            except TypeError:
                pass
            except Exception as exc:
                self._warn_once("mark", "draw_map with the start mark failed ({}); drawing without it".format(exc))
        if self.plan and occ is not None:
            try:
                return self.draw_map(items, robot_pose=pose, occupancy=occ, path=trail, plan=self.plan)
            except TypeError:
                pass        # an older draw_map without `plan`: draw without it
            except Exception as exc:
                self._warn_once("plan", "draw_map with the plan failed ({}); drawing without it".format(exc))
        if occ is not None:
            try:
                return self.draw_map(items, robot_pose=pose, occupancy=occ, path=trail)
            except Exception as exc:
                self._warn_once("occ", "draw_map with map_yaml={} failed ({}); drawing without it".format(occ, exc))
        try:
            return self.draw_map(items, robot_pose=pose, path=trail)
        except Exception as exc:
            self._warn_once("draw", "draw_map failed ({}: {}); using the plain drawing".format(
                type(exc).__name__, exc))
            return compat.plain_draw_map(items, robot_pose=pose)

    def render_png(self):
        items = self.shared.memory.items
        pose = self.shared.robot_pose
        key = (self.shared.memory.version, getattr(self, "plan_version", 0), self.trail.version,
               None if pose is None else (round(pose.x, 2), round(pose.y, 2), round(pose.yaw, 2)))
        with self._png_lock:
            if self._png is None or key != self._png_key:
                self._png = self._draw(items, pose)
                self._png_key = key
            return self._png

    def _handler(self):
        node = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def _send(self, code, ctype, body):
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                path = self.path.split("?")[0]
                try:
                    if path in ("/", "/index.html"):
                        self._send(200, "text/html; charset=utf-8", node.page.encode("utf-8"))
                    elif path == "/map.png":
                        self._send(200, "image/png", node.render_png())
                    elif path == "/items.json":
                        body = json.dumps({"status": node.status,
                                           "items": core.items_json(node.shared.memory.items)})
                        self._send(200, "application/json", body.encode("utf-8"))
                    else:
                        self._send(404, "text/plain", b"not found")
                except Exception as exc:
                    self._send(500, "text/plain", str(exc).encode("utf-8"))
        return H

    def shutdown_server(self):
        self.server.shutdown()
        self.server.server_close()


# ---------------------------------------------------------------- entry points
def _spin(nodes, on_exit=None):
    executor = MultiThreadedExecutor(num_threads=4)
    for n in nodes:
        executor.add_node(n)
    try:
        executor.spin()
    except KeyboardInterrupt:
        pass
    except Exception as exc:  # ExternalShutdownException on Humble
        if type(exc).__name__ != "ExternalShutdownException":
            raise
    finally:
        if on_exit is not None:
            # Ctrl-C in tmux reaches this process twice (terminal + ros2 launch);
            # ignore further SIGINTs so the final save completes.
            import signal
            signal.signal(signal.SIGINT, signal.SIG_IGN)
            on_exit()
        for n in nodes:
            n.destroy_node()
        try:
            rclpy.shutdown()
        except Exception:
            pass


def main_all(args=None):
    """observer + finder + mapview in one process, one shared memory."""
    rclpy.init(args=args)
    observer = ObserverNode()
    shared = observer.shared
    finder = FinderNode(shared=shared)
    mapview = MapviewNode(shared=shared)
    finder.core.on_change = observer.core.mark_dirty  # confidences changed by a search get saved

    def on_exit():
        observer.save_now()
        mapview.shutdown_server()
    _spin([observer, finder, mapview], on_exit)


def main_observer(args=None):
    rclpy.init(args=args)
    node = ObserverNode()
    _spin([node], node.save_now)


def main_finder(args=None):
    rclpy.init(args=args)
    node = FinderNode()
    _spin([node])


def main_mapview(args=None):
    rclpy.init(args=args)
    node = MapviewNode()
    _spin([node], node.shutdown_server)


if __name__ == "__main__":
    main_all(sys.argv)
