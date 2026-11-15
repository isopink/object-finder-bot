"""A scripted vision worker for the ROS tests (standard library + numpy).

Follows the worker HTTP contract of the brief. `/verify` answers from a list
(e.g. [False, True]: the first re-check fails, the second succeeds), and
`/embed_text` returns a fixed embedding so the candidate order is known.

    python fake_worker.py --port 8600 --verify false,true
"""
import argparse
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import numpy as np

DIM = 512


def unit(seed):
    v = np.random.RandomState(seed).randn(DIM).astype(np.float32)
    return v / np.linalg.norm(v)


def mix(a, b, wa, wb):
    v = wa * a + wb * b
    return (v / np.linalg.norm(v)).astype(np.float32)


# Two remembered objects and a query closer to the first one.
EMB_A = unit(1)
EMB_B = unit(2)
EMB_QUERY = mix(EMB_A, EMB_B, 1.0, 0.8)


class FakeWorker(object):
    def __init__(self, port=0, verify_script=(False, True), detections=None):
        self.verify_script = list(verify_script)
        self.detections = detections or []
        self.calls = []
        worker = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _reply(self, obj):
                body = json.dumps(obj).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                worker.calls.append(("GET", self.path, None))
                self._reply({"ok": True, "camera": True, "camera_mode": "depth"})

            def do_POST(self):
                n = int(self.headers.get("Content-Length", "0"))
                req = json.loads(self.rfile.read(n).decode("utf-8") or "{}")
                worker.calls.append(("POST", self.path, req))
                if self.path == "/embed_text":
                    self._reply({"embedding": EMB_QUERY.tolist()})
                elif self.path == "/verify":
                    i = sum(1 for c in worker.calls if c[1] == "/verify") - 1
                    found = worker.verify_script[i] if i < len(worker.verify_script) else False
                    self._reply({"found": bool(found), "prob": 0.9 if found else 0.1,
                                 "box": [10, 10, 50, 50] if found else None})
                elif self.path == "/detect_embed":
                    self._reply({"t": 0.0, "detections": worker.detections})
                else:
                    self.send_response(404)
                    self.end_headers()

        self.server = HTTPServer(("127.0.0.1", port), H)
        self.port = self.server.server_address[1]
        self.url = "http://127.0.0.1:{}".format(self.port)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def start(self):
        self.thread.start()
        return self

    def stop(self):
        self.server.shutdown()
        self.server.server_close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8600)
    ap.add_argument("--verify", default="false,true")
    a = ap.parse_args()
    script = [s.strip().lower() == "true" for s in a.verify.split(",") if s.strip()]
    w = FakeWorker(a.port, script)
    print("fake worker on {}".format(w.url), flush=True)
    w.server.serve_forever()


if __name__ == "__main__":
    main()
