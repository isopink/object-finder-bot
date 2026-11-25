"""Live SLAM map in a browser: /map + the robot pose (TF map -> base_link) -> PNG over HTTP.

Run while slam.sh runs (ROS Python, no conda):
  source robot/env.sh && python3 robot/lib/live_map.py      # then open http://<jetson-ip>:8556/
The page refreshes every second: white free, black occupied, gray unknown, red dot and
line = robot and heading, green circle = map origin, blue = path since the viewer started.
Written on 2026-11-25 to see whether a turn shows up in the map while driving.
"""
import io
import math
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn

import numpy as np
import rclpy
from nav_msgs.msg import OccupancyGrid
from PIL import Image, ImageDraw
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from tf2_ros import Buffer, TransformListener

PORT = 8556
SCALE = 4
state = {"png": None, "info": "waiting for /map ...", "trail": []}
lock = threading.Lock()


class LiveMap(object):
    def __init__(self, node):
        self.node = node
        self.map = None
        qos = QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL,
                         reliability=ReliabilityPolicy.RELIABLE)
        node.create_subscription(OccupancyGrid, "/map", self.on_map, qos)
        self.tf = Buffer()
        self.tfl = TransformListener(self.tf, node)
        node.create_timer(0.5, self.render)

    def on_map(self, m):
        self.map = m

    def pose(self):
        try:
            t = self.tf.lookup_transform("map", "base_link", rclpy.time.Time())
        except Exception:  # noqa: BLE001
            return None
        q = t.transform.rotation
        yaw = math.atan2(2 * (q.w * q.z + q.x * q.y), 1 - 2 * (q.y * q.y + q.z * q.z))
        return t.transform.translation.x, t.transform.translation.y, yaw

    def render(self):
        m = self.map
        if m is None:
            return
        w, h, res = m.info.width, m.info.height, m.info.resolution
        ox, oy = m.info.origin.position.x, m.info.origin.position.y
        g = np.array(m.data, dtype=np.int16).reshape(h, w)
        rgb = np.full((h, w, 3), 205, np.uint8)            # unknown: gray
        rgb[(g >= 0) & (g < 25)] = (255, 255, 255)          # free: white
        rgb[g >= 65] = (20, 20, 20)                         # occupied: black
        img = Image.fromarray(rgb[::-1], "RGB").resize((w * SCALE, h * SCALE), Image.NEAREST)
        d = ImageDraw.Draw(img)
        to_px = lambda x, y: ((x - ox) / res * SCALE, (h - (y - oy) / res) * SCALE)
        # map origin (start point)
        sx, sy = to_px(0.0, 0.0)
        d.ellipse([sx - 6, sy - 6, sx + 6, sy + 6], outline=(0, 160, 0), width=3)
        p = self.pose()
        if p is not None:
            tr = state["trail"]
            if not tr or math.hypot(tr[-1][0] - p[0], tr[-1][1] - p[1]) > 0.05:
                tr.append((p[0], p[1]))
                del tr[:-2000]
            if len(tr) > 1:
                d.line([to_px(x, y) for x, y in tr], fill=(80, 140, 255), width=2)
            px, py = to_px(p[0], p[1])
            r = 0.15 / res * SCALE
            d.ellipse([px - r, py - r, px + r, py + r], fill=(230, 50, 50))
            hx, hy = to_px(p[0] + 0.35 * math.cos(p[2]), p[1] + 0.35 * math.sin(p[2]))
            d.line([px, py, hx, hy], fill=(230, 50, 50), width=4)
            info = "robot x %.2f y %.2f yaw %.0f deg" % (p[0], p[1], math.degrees(p[2]))
        else:
            info = "robot pose: waiting for TF map -> base_link"
        free = int(((g >= 0) & (g < 25)).sum())
        info += " | map %.1f x %.1f m, free %.1f m2 | %s" % (w * res, h * res, free * res * res,
                                                            time.strftime("%H:%M:%S"))
        buf = io.BytesIO()
        img.save(buf, "PNG")
        with lock:
            state["png"], state["info"] = buf.getvalue(), info


PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>Live SLAM</title>
<style>body{margin:0;background:#222;color:#eee;font:14px sans-serif}
#i{padding:6px 10px}img{max-width:100vw;max-height:calc(100vh - 34px);display:block;margin:auto}</style></head>
<body><div id="i">loading...</div><img id="m">
<script>
async function tick(){
  try{const r=await fetch('/info');document.getElementById('i').textContent=await r.text();
      document.getElementById('m').src='/map.png?'+Date.now();}catch(e){}
  setTimeout(tick,1000);}
tick();
</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        with lock:
            png, info = state["png"], state["info"]
        if self.path.startswith("/map.png"):
            if png is None:
                self.send_response(503); self.end_headers(); return
            body, ctype = png, "image/png"
        elif self.path.startswith("/info"):
            body, ctype = info.encode("utf-8"), "text/plain; charset=utf-8"
        else:
            body, ctype = PAGE.encode("utf-8"), "text/html; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)


class Server(ThreadingMixIn, HTTPServer):
    daemon_threads = True


def main():
    rclpy.init()
    node = rclpy.create_node("live_map_viewer")
    LiveMap(node)
    srv = Server(("0.0.0.0", PORT), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    print("live map on http://<jetson-ip>:%d/" % PORT, flush=True)
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    srv.shutdown()


if __name__ == "__main__":
    main()
