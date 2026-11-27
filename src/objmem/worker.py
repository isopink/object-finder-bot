"""Vision worker: HTTP/JSON server and client (standard library only).

The worker runs in the conda env (no ROS) and holds one embedder, one detector
and optionally one camera. Requests are handled one at a time.

  GET  /health        -> {"ok": true, "camera": bool, "camera_mode": str}
  POST /detect_embed  {"image_jpeg_b64": str or absent}
                      -> {"t": float, "detections": [{"box", "label", "conf", "embedding", "depth_m"}]}
  POST /verify        {"text": str, "image_jpeg_b64": str or absent}
                      -> {"found": bool, "prob": float, "box": [l,t,r,b] or null}
  POST /embed_text    {"text": str} -> {"embedding": [512 floats]}

Without `image_jpeg_b64` the worker reads its own camera and fills `depth_m`
from the camera's depth image (null in nodepth mode). With an image, `depth_m`
is null and the caller looks depth up itself. When the detector returns
nothing, /detect_embed embeds the 3x3 tiles of the frame instead (labels
tile<r><c>, conf 0.0).

JPEG coding uses PIL, imported only when an image is actually sent.
"""
import base64
import io
import json
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn
from typing import List, Optional, Tuple

import numpy as np

from objmem.crops import detection_crops, grid_crops
from objmem.embed import CachedTextEmbedder
from objmem.geometry import median_depth
from objmem.types import Detection, Params
from objmem.verify import check_frame

DEFAULT_PORT = 8600


# ---------------------------------------------------------------- JPEG helpers
def encode_jpeg_b64(color: np.ndarray, quality: int = 90) -> str:
    """RGB uint8 (H, W, 3) -> base64 JPEG string."""
    from PIL import Image

    buf = io.BytesIO()
    Image.fromarray(np.ascontiguousarray(color[:, :, :3]).astype(np.uint8), "RGB").save(buf, format="JPEG", quality=quality)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def decode_jpeg_b64(data: str) -> np.ndarray:
    """base64 JPEG (or PNG) string -> RGB uint8 (H, W, 3)."""
    from PIL import Image

    raw = base64.b64decode(data)
    with Image.open(io.BytesIO(raw)) as im:
        return np.asarray(im.convert("RGB"), dtype=np.uint8).copy()


# ---------------------------------------------------------------- server
class HttpError(Exception):
    def __init__(self, code: int, message: str):
        Exception.__init__(self, message)
        self.code = code
        self.message = message


class VisionService:
    """The request logic, independent of HTTP (also usable in-process)."""

    def __init__(self, embedder, detector, camera=None, params: Optional[Params] = None,
                 camera_mode: Optional[str] = None, tiles: bool = True):
        self.params = params if params is not None else Params()
        self.embedder = embedder if isinstance(embedder, CachedTextEmbedder) else CachedTextEmbedder(embedder)
        self.detector = detector
        self.camera = camera
        self.camera_mode = camera_mode or self.params.camera_mode
        self.tiles = bool(tiles)   # False: an empty detector result stays empty (no tile crops)
        self.lock = threading.Lock()
        # For the live view (view_jpeg): what the last detection / re-check saw.
        self.last_color = None      # RGB frame of the last camera read
        self.last_boxes = (0.0, [])  # (time, [(box, text)]) of the last /detect_embed on the camera
        self.last_verify = (0.0, "", None)  # (time, text, box or None) of the last /verify
        self._view_skip_until = 0.0  # the view does not read a camera that just gave no frame

    # -- inputs
    def _frame(self, body: dict):
        """(color, depth or None, t, from_camera)."""
        data = body.get("image_jpeg_b64")
        if data:
            try:
                color = decode_jpeg_b64(data)
            except Exception as exc:
                raise HttpError(400, "cannot decode image_jpeg_b64: {}".format(exc))
            return color, None, time.time(), False
        if self.camera is None:
            raise HttpError(503, "no camera attached and no image_jpeg_b64 sent")
        frame = self.camera.read()
        if frame is None:
            raise HttpError(503, "no frame from the camera")
        self.last_color = frame.color
        return frame.color, frame.depth, float(frame.t), True

    # -- endpoints
    def health(self) -> dict:
        return {"ok": True, "camera": self.camera is not None, "camera_mode": self.camera_mode}

    def detect_embed(self, body: dict) -> dict:
        color, depth, t, from_camera = self._frame(body)
        boxes = self.detector.detect(color)
        # embed the padded crop, report the detector's own box
        kept = []
        for rb in boxes:
            pad_crop = detection_crops(color, [rb], pad=float(self.params.crop_pad))
            if pad_crop:
                kept.append((pad_crop[0].image, tuple(int(v) for v in rb.box), rb.label, float(rb.conf)))
        if not kept and self.tiles:
            kept = [(c.image, tuple(int(v) for v in c.box), c.label, 0.0) for c in grid_crops(color, 3)]
        vecs = self.embedder.embed_images([k[0] for k in kept]) if kept else np.zeros((0, 512), np.float32)
        out = []
        for (img, box, label, cf), vec in zip(kept, vecs):
            d = None
            if depth is not None:
                d = median_depth(depth, box)
            out.append({"box": list(box), "label": str(label), "conf": cf,
                        "embedding": [float(x) for x in vec], "depth_m": d})
        if from_camera:
            self.last_boxes = (time.time(), [
                (o["box"], "{} {:.2f}{}".format(o["label"], o["conf"],
                                               "" if o["depth_m"] is None else "  {:.2f} m".format(o["depth_m"])))
                for o in out if o["conf"] > 0.0])
        return {"t": t, "detections": out}

    def verify(self, body: dict) -> dict:
        text = body.get("text")
        if not isinstance(text, str) or not text.strip():
            raise HttpError(400, "'text' must be a non-empty string")
        color, _, _, _ = self._frame(body)
        boxes = self.detector.detect(color)
        found, prob, box = check_frame(color, boxes, text, self.embedder, self.params)
        self.last_verify = (time.time(), "re-check '{}': {} (p={:.2f})".format(
            text, "FOUND" if found else "not found", prob), list(box) if (found and box is not None) else None)
        return {"found": bool(found), "prob": float(prob), "box": list(box) if box is not None else None}

    def view_jpeg(self, quality: int = 70) -> bytes:
        """The camera image as JPEG with the boxes of the last detection (kept 2 s) and the last
        re-check (kept 8 s). Reads a fresh frame; falls back to the last one. For people only:
        the live view server calls it, nothing in the robot depends on it."""
        from PIL import Image, ImageDraw

        with self.lock:
            color = None
            if self.camera is not None and time.time() >= self._view_skip_until:
                frame = self.camera.read()
                if frame is not None:
                    color = self.last_color = frame.color
                else:       # a stalled camera blocks for seconds: leave it to the robot's own requests
                    self._view_skip_until = time.time() + 5.0
            if color is None:
                color = self.last_color
            t_box, boxes = self.last_boxes
            t_ver, ver_text, ver_box = self.last_verify
        if color is None:
            raise HttpError(503, "no frame from the camera")
        now = time.time()
        im = Image.fromarray(np.ascontiguousarray(color[:, :, :3]).astype(np.uint8), "RGB")
        draw = ImageDraw.Draw(im)

        def box_with_text(box, text, rgb):
            l, t, r, b = [int(v) for v in box]
            for k in range(3):
                draw.rectangle([l - k, t - k, r + k, b + k], outline=rgb)
            w = 6 * len(text) + 6
            y = t - 14 if t >= 14 else b + 2
            draw.rectangle([l, y, l + w, y + 12], fill=rgb)
            draw.text((l + 3, y + 1), text, fill=(0, 0, 0))

        if now - t_box <= 2.0:
            for box, text in boxes:
                box_with_text(box, text, (60, 230, 60))
        if now - t_ver <= 8.0:
            if ver_box is not None:
                box_with_text(ver_box, ver_text, (255, 220, 0))
            else:
                draw.rectangle([0, 0, 6 * len(ver_text) + 8, 13], fill=(255, 220, 0))
                draw.text((4, 1), ver_text, fill=(0, 0, 0))
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=int(quality))
        return buf.getvalue()

    def embed_text(self, body: dict) -> dict:
        text = body.get("text")
        if not isinstance(text, str):
            raise HttpError(400, "'text' must be a string")
        return {"embedding": [float(x) for x in self.embedder.embed_text(text)]}

    def handle(self, method: str, path: str, body: Optional[dict]) -> dict:
        path = path.split("?", 1)[0].rstrip("/") or "/"
        routes = {
            ("GET", "/health"): lambda b: self.health(),
            ("POST", "/detect_embed"): self.detect_embed,
            ("POST", "/verify"): self.verify,
            ("POST", "/embed_text"): self.embed_text,
        }
        fn = routes.get((method, path))
        if fn is None:
            raise HttpError(404, "no endpoint {} {}".format(method, path))
        with self.lock:
            return fn(body or {})


class _Handler(BaseHTTPRequestHandler):
    service = None  # type: VisionService
    quiet = True

    def _send(self, code: int, obj: dict) -> None:
        data = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _run(self, method: str) -> None:
        try:
            body = None
            if method == "POST":
                n = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(n) if n > 0 else b""
                try:
                    body = json.loads(raw.decode("utf-8")) if raw else {}
                except ValueError:
                    raise HttpError(400, "request body is not JSON")
                if not isinstance(body, dict):
                    raise HttpError(400, "request body must be a JSON object")
            self._send(200, self.service.handle(method, self.path, body))
        except HttpError as exc:
            self._send(exc.code, {"error": exc.message})
        except Exception as exc:  # report, keep serving
            import traceback
            traceback.print_exc()
            self._send(500, {"error": "{}: {}".format(type(exc).__name__, exc)})

    def do_GET(self):
        self._run("GET")

    def do_POST(self):
        self._run("POST")

    def log_message(self, fmt, *args):
        if not self.quiet:
            BaseHTTPRequestHandler.log_message(self, fmt, *args)


VIEW_PAGE = b"""<!doctype html><html><head><meta charset="utf-8"><title>Robot camera</title>
<style>body{margin:0;background:#111;color:#ddd;font:14px sans-serif;text-align:center}
img{max-width:100vw;max-height:calc(100vh - 30px)}#s{padding:5px}</style></head><body>
<div id="s">robot camera: green = detection, yellow = re-check</div><img id="i">
<script>
var i=document.getElementById("i"),s=document.getElementById("s"),n=0,bad=0;
function next(){var im=new Image();
 im.onload=function(){i.src=im.src;bad=0;n++;s.textContent="robot camera: green = detection, yellow = re-check  ("+n+")";setTimeout(next,250)};
 im.onerror=function(){bad++;s.textContent="no image from the worker ("+bad+")";setTimeout(next,1500)};
 im.src="/view.jpg?"+Date.now()}
next();
</script></body></html>"""


class _ViewHandler(BaseHTTPRequestHandler):
    service = None  # type: VisionService
    timeout = 10     # an idle browser connection must not hold a thread for ever

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        try:
            if path in ("/", "/view"):
                body, ctype = VIEW_PAGE, "text/html; charset=utf-8"
            elif path == "/view.jpg":
                body, ctype = self.service.view_jpeg(), "image/jpeg"
            else:
                self.send_error(404)
                return
        except HttpError as exc:
            self.send_error(exc.code, exc.message)
            return
        except Exception as exc:  # noqa: BLE001 - the view must never hurt the worker
            self.send_error(500, "{}: {}".format(type(exc).__name__, exc))
            return
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        pass


class _ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True


def start_view_server(service: "VisionService", host: str = "0.0.0.0", port: int = 8601) -> HTTPServer:
    """Live camera view for people, on its own port and threads: a browser that keeps a
    connection open can then never block the (single-threaded) worker port.
    port=0 picks a free port: see server.server_address. Returns the running server."""
    handler = type("ViewHandler", (_ViewHandler,), {"service": service})
    server = _ThreadingHTTPServer((host, port), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def make_server(embedder, detector, camera=None, params: Optional[Params] = None,
                host: str = "0.0.0.0", port: int = DEFAULT_PORT, camera_mode: Optional[str] = None,
                quiet: bool = True, tiles: bool = True) -> HTTPServer:
    """Build the (single-threaded) HTTP server. port=0 picks a free port: see server.server_address."""
    service = VisionService(embedder, detector, camera, params, camera_mode, tiles=tiles)
    handler = type("VisionHandler", (_Handler,), {"service": service, "quiet": quiet})
    server = HTTPServer((host, port), handler)
    server.service = service
    return server


def serve(embedder, detector, camera=None, params: Optional[Params] = None,
          host: str = "0.0.0.0", port: int = DEFAULT_PORT, camera_mode: Optional[str] = None,
          quiet: bool = False, block: bool = True, tiles: bool = True, view_port: int = 0):
    """Run the worker. block=True serves until Ctrl+C; block=False starts a daemon thread
    and returns the server (call server.shutdown() to stop). view_port > 0 also serves the
    live camera view (start_view_server) there."""
    server = make_server(embedder, detector, camera, params, host, port, camera_mode, quiet, tiles)
    if view_port:
        try:
            server.view_server = start_view_server(server.service, host, int(view_port))
        except OSError as exc:      # the view is a convenience: never stop the worker for it
            print("[WARN] live view not started on port {}: {}".format(view_port, exc), flush=True)
    if not block:
        threading.Thread(target=server.serve_forever, daemon=True).start()
        return server
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return server


# ---------------------------------------------------------------- client
class VisionWorkerError(RuntimeError):
    """The worker answered with an error, or could not be reached."""


class VisionClient:
    """Client for the worker. `color` arguments are RGB uint8 arrays; None = worker's camera."""

    def __init__(self, url: str = "http://127.0.0.1:8600", timeout: float = 10.0):
        self.url = url.rstrip("/")
        self.timeout = float(timeout)
        self.last_t = None  # type: Optional[float]

    def _call(self, method: str, path: str, body: Optional[dict] = None) -> dict:
        data = None
        headers = {}
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(self.url + path, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            try:
                msg = json.loads(exc.read().decode("utf-8")).get("error", "")
            except Exception:
                msg = ""
            raise VisionWorkerError("{} {} -> HTTP {}: {}".format(method, path, exc.code, msg))
        except (urllib.error.URLError, OSError) as exc:
            raise VisionWorkerError("cannot reach the vision worker at {}: {}".format(self.url, exc))

    @staticmethod
    def _image_body(color: Optional[np.ndarray]) -> dict:
        return {} if color is None else {"image_jpeg_b64": encode_jpeg_b64(color)}

    def health(self) -> dict:
        return self._call("GET", "/health")

    def detect_embed_raw(self, color: Optional[np.ndarray] = None) -> dict:
        return self._call("POST", "/detect_embed", self._image_body(color))

    def detect_embed(self, color: Optional[np.ndarray] = None) -> List[Detection]:
        """Detections with embeddings. The frame time is kept in self.last_t."""
        res = self.detect_embed_raw(color)
        self.last_t = float(res.get("t", time.time()))
        out = []
        for d in res.get("detections", []):
            emb = np.asarray(d["embedding"], dtype=np.float32)
            dm = d.get("depth_m")
            out.append(Detection(box=tuple(int(v) for v in d["box"]), label=str(d.get("label", "")),
                                 conf=float(d.get("conf", 0.0)), embedding=emb,
                                 depth_m=None if dm is None else float(dm)))
        return out

    def verify_full(self, text: str, color: Optional[np.ndarray] = None) -> Tuple[bool, float, Optional[Tuple[int, int, int, int]]]:
        body = {"text": text}
        body.update(self._image_body(color))
        res = self._call("POST", "/verify", body)
        box = res.get("box")
        return bool(res["found"]), float(res["prob"]), (tuple(int(v) for v in box) if box else None)

    def verify(self, text: str, color: Optional[np.ndarray] = None) -> Tuple[bool, float]:
        found, prob, _ = self.verify_full(text, color)
        return found, prob

    def embed_text(self, text: str) -> np.ndarray:
        res = self._call("POST", "/embed_text", {"text": text})
        return np.asarray(res["embedding"], dtype=np.float32)


class ClientVerifier:
    """Verifier that re-checks the worker's live camera view."""

    def __init__(self, client: VisionClient):
        self.client = client
        self.last_box = None

    def check(self, text: str) -> Tuple[bool, float]:
        found, prob, box = self.client.verify_full(text)
        self.last_box = box
        return found, prob


class ClientEmbedder:
    """Embedder (text only) backed by the worker, e.g. for search.find on the ROS side."""

    def __init__(self, client: VisionClient):
        self.client = client

    def embed_text(self, text: str) -> np.ndarray:
        return self.client.embed_text(text)

    def embed_images(self, images):
        raise NotImplementedError("ClientEmbedder embeds text only; send frames to /detect_embed")
