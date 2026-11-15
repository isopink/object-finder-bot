"""Smoke test of objmem.launch.py (run by .github/workflows/ros.yml).

Launches observer + finder + mapview in one process with the repo config and a
fake worker, publishes a static map -> base_link TF so the observer steps,
checks the mapview page, PNG, JSON, and /objmem/markers, then stops the
launch with SIGINT and checks that the memory file was saved on shutdown.

    python3 ros/objmem_ros/test/ros_launch_smoke.py <repo>/config/default.yaml
"""
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from fake_worker import EMB_A, FakeWorker  # noqa: E402

PORT = 8555


def get(path):
    with urllib.request.urlopen("http://127.0.0.1:{}{}".format(PORT, path), timeout=5) as r:
        return r.read()


def main():
    import rclpy
    from rclpy.node import Node
    from std_msgs.msg import String
    from visualization_msgs.msg import MarkerArray

    config = sys.argv[1] if len(sys.argv) > 1 else ""
    tmp = tempfile.mkdtemp(prefix="objmem_launch_")
    mem_path = os.path.join(tmp, "memory.npz")
    dets = [{"box": [300, 200, 340, 280], "label": "mug", "conf": 0.9, "embedding": EMB_A.tolist(),
             "depth_m": 1.5}]
    worker = FakeWorker(0, [True], detections=dets).start()
    log = open(os.path.join(tmp, "launch.log"), "w")
    cmd = ["ros2", "launch", "objmem_ros", "objmem.launch.py", "config:=" + config,
           "memory_file:=" + mem_path, "image_source:=worker", "worker_url:=" + worker.url,
           "observe_rate:=2.0", "only_when_stopped:=true"]
    print("+ " + " ".join(cmd), flush=True)
    launch = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, preexec_fn=os.setsid)
    tf = subprocess.Popen(["ros2", "run", "tf2_ros", "static_transform_publisher",
                           "0", "0", "0", "0", "0", "0", "map", "base_link"],
                          stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT, preexec_fn=os.setsid)

    rclpy.init()
    node = Node("objmem_launch_smoke")
    seen = {"status": [], "markers": 0}
    node.create_subscription(String, "/objmem/status", lambda m: seen["status"].append(m.data), 10)
    node.create_subscription(MarkerArray, "/objmem/markers",
                             lambda m: seen.__setitem__("markers", max(seen["markers"], len(m.markers))), 10)
    ok = False
    try:
        t0 = time.time()
        page = png = items = None
        while time.time() - t0 < 60.0:
            rclpy.spin_once(node, timeout_sec=0.2)
            try:
                page, png = get("/"), get("/map.png")
                items = json.loads(get("/items.json").decode("utf-8"))
            except Exception:
                continue
            if items["items"] and seen["markers"] >= 3 and any(s.startswith("observe:") for s in seen["status"]):
                break
        print("status: {}".format(seen["status"][-3:]), flush=True)
        print("items: {}".format(items), flush=True)
        assert page is not None and b"objmem map" in page
        assert png is not None and png[:4] == b"\x89PNG"
        assert items is not None and len(items["items"]) == 1, items
        assert seen["markers"] >= 3, seen  # DELETEALL + ellipse + label
        os.killpg(os.getpgid(launch.pid), signal.SIGINT)
        launch.wait(20)
        assert os.path.exists(mem_path), "memory not saved on shutdown"
        ok = True
    finally:
        node.destroy_node()
        rclpy.shutdown()
        for p in (launch, tf):
            if p.poll() is None:
                os.killpg(os.getpgid(p.pid), signal.SIGKILL)
        worker.stop()
        log.close()
        print("----- launch log -----")
        with open(log.name) as f:
            print(f.read())
    print("LAUNCH SMOKE PASSED" if ok else "LAUNCH SMOKE FAILED", flush=True)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
