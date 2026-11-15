"""End-to-end ROS test of the finder (run by .github/workflows/ros.yml).

Needs a sourced ROS 2 install with objmem_ros built, nav2_msgs, and objmem
importable. Starts:

- the scripted fake vision worker (first re-check fails, second succeeds),
- `ros2 run objmem_ros fake_nav2` (accepts every goal),
- `ros2 run objmem_ros finder` with a preloaded two-object memory file,

publishes one query on /query, and checks the /objmem/status sequence:
goal sent, re-check fails, next goal sent, re-check succeeds, result found.

    python3 ros/objmem_ros/test/ros_e2e.py
"""
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from objmem.types import Params  # noqa: E402

from objmem_ros import compat, core  # noqa: E402

import helpers  # noqa: E402
from fake_worker import FakeWorker  # noqa: E402

TIMEOUT_S = 90.0


def start(cmd, log):
    print("+ " + " ".join(cmd), flush=True)
    return subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, preexec_fn=os.setsid)


def stop(proc):
    if proc.poll() is None:
        os.killpg(os.getpgid(proc.pid), signal.SIGINT)
        try:
            proc.wait(10)
        except subprocess.TimeoutExpired:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)


def main():
    import rclpy
    from rclpy.node import Node
    from std_msgs.msg import String

    tmp = tempfile.mkdtemp(prefix="objmem_e2e_")
    mem_path = os.path.join(tmp, "memory.npz")
    params = Params()
    memory = helpers.preload(compat.memory_class()(params), time.time())
    core.save_memory(memory, mem_path)
    print("memory: {} items in {} (stand-ins: {})".format(len(memory.items), mem_path,
                                                        compat.FALLBACKS or "none"), flush=True)

    worker = FakeWorker(0, [False, True]).start()
    print("fake worker: " + worker.url, flush=True)

    logs = {n: open(os.path.join(tmp, n + ".log"), "w") for n in ("nav", "finder")}
    nav = start(["ros2", "run", "objmem_ros", "fake_nav2", "--delay", "0.5"], logs["nav"])
    finder = start(["ros2", "run", "objmem_ros", "finder", "--ros-args",
                    "-p", "memory_file:=" + mem_path, "-p", "worker_url:=" + worker.url,
                    "-p", "nav_timeout_s:=30.0"], logs["finder"])

    rclpy.init()
    node = Node("objmem_e2e")
    lines = []
    done = threading.Event()

    def on_status(msg):
        lines.append(msg.data)
        print("status: " + msg.data, flush=True)
        if msg.data.startswith("result:") or msg.data.startswith("error:"):
            done.set()
    node.create_subscription(String, "/objmem/status", on_status, 10)
    pub = node.create_publisher(String, "/query", 10)

    ok = False
    try:
        t0 = time.time()
        # Wait until the finder subscribes to /query.
        while pub.get_subscription_count() == 0 and time.time() - t0 < 30.0:
            rclpy.spin_once(node, timeout_sec=0.2)
        if pub.get_subscription_count() == 0:
            raise RuntimeError("finder never subscribed to /query")
        msg = String()
        msg.data = "where is the mug"
        pub.publish(msg)
        while not done.is_set() and time.time() - t0 < TIMEOUT_S:
            rclpy.spin_once(node, timeout_sec=0.2)
        kinds = [l.split(":")[0] for l in lines]
        expected = ["query", "candidates", "goal_sent", "goal_reached", "recheck",
                    "goal_sent", "goal_reached", "recheck", "result"]
        print("kinds: {}".format(kinds), flush=True)
        assert kinds == expected, "status sequence {} != {}".format(kinds, expected)
        assert lines[4].startswith("recheck: not_found"), lines[4]
        assert lines[7].startswith("recheck: found"), lines[7]
        assert lines[8].startswith("result: found"), lines[8]
        verifies = [c for c in worker.calls if c[1] == "/verify"]
        assert len(verifies) == 2, worker.calls
        # The standalone finder writes the updated confidences back to the file.
        time.sleep(0.5)
        mem2, loaded = core.load_or_create_memory(mem_path, params)
        assert loaded and len(mem2.items) == 2
        ok = True
    finally:
        node.destroy_node()
        rclpy.shutdown()
        stop(finder)
        stop(nav)
        worker.stop()
        for name, fh in logs.items():
            fh.close()
            print("----- {} log -----".format(name))
            with open(fh.name) as f:
                print(f.read())
    print("E2E PASSED" if ok else "E2E FAILED", flush=True)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
