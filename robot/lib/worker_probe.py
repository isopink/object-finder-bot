#!/usr/bin/env python3
"""Probe the vision worker over HTTP and time each endpoint.

Usage: python3 robot/lib/worker_probe.py [--url http://127.0.0.1:8600] [--mode depth|nodepth]
                                         [--n 5] [--query "a cup"] [--wait 0]

Prints [OK]/[FAIL] lines and a timing table. Uses only the worker's own camera
(no image in the request). Standard library only. Python 3.8 syntax.
"""
import argparse
import json
import sys
import time
import urllib.error
import urllib.request

N_FAIL = 0


def ok(msg):
    print("  [OK]   " + msg)


def fail(msg, hint=""):
    global N_FAIL
    N_FAIL += 1
    print("  [FAIL] " + msg)
    if hint:
        print("         hint: " + hint)


def call(url, path, body=None, timeout=60.0):
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url + path, data=data, headers={"Content-Type": "application/json"})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=timeout) as r:
        out = json.loads(r.read().decode("utf-8"))
    return out, time.time() - t0


def wait_health(url, wait_s):
    deadline = time.time() + wait_s
    while True:
        try:
            return call(url, "/health", timeout=3.0)[0]
        except Exception as e:  # noqa: BLE001
            if time.time() >= deadline:
                raise e
            time.sleep(2.0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8600")
    ap.add_argument("--mode", choices=["depth", "nodepth"], default=None)
    ap.add_argument("--n", type=int, default=5)
    ap.add_argument("--query", default="a cup")
    ap.add_argument("--wait", type=float, default=0.0, help="seconds to wait for /health")
    args = ap.parse_args()
    url = args.url.rstrip("/")

    try:
        h = wait_health(url, args.wait)
    except Exception as e:  # noqa: BLE001
        fail("GET /health: %s" % e, "is the worker running? ./robot/check_stage4.sh starts one")
        return 1
    print("  health: %s" % json.dumps(h))
    if h.get("ok"):
        ok("worker is up")
    else:
        fail("worker reports ok=false", "read the worker log")
    if h.get("camera"):
        ok("worker has a camera")
    else:
        fail("worker has no camera", "plug in the camera, check --camera realsense|c920, see lsusb")
    if args.mode is not None:
        if h.get("camera_mode") == args.mode:
            ok("camera_mode is %s" % args.mode)
        else:
            fail("camera_mode is %r, expected %r" % (h.get("camera_mode"), args.mode),
                 "the worker reads camera_mode from --config; start_all.sh writes it for you")

    # One untimed warm-up call: the first /detect_embed builds the TensorRT
    # engine and loads CLIP (8 s on 2026-11-18) and would fail the 3 s limit.
    try:
        _, dt0 = call(url, "/detect_embed", {})
        print("  warm-up /detect_embed: %.0f ms (not counted)" % (1000 * dt0))
    except Exception as e:  # noqa: BLE001
        print("  warm-up /detect_embed failed: %s" % e)

    times = []
    n_det = []
    depth_seen = 0
    labels = {}
    for i in range(max(1, args.n)):
        try:
            out, dt = call(url, "/detect_embed", {})
        except Exception as e:  # noqa: BLE001
            fail("POST /detect_embed #%d: %s" % (i + 1, e), "read the worker log (camera timeout? out of memory?)")
            break
        dets = out.get("detections", [])
        times.append(dt)
        n_det.append(len(dets))
        for d in dets:
            labels[d.get("label", "?")] = labels.get(d.get("label", "?"), 0) + 1
            emb = d.get("embedding") or []
            if len(emb) != 512:
                fail("embedding length %d, expected 512" % len(emb))
                break
            if d.get("depth_m") is not None:
                depth_seen += 1
    if times:
        ok("/detect_embed x%d: mean %.0f ms, max %.0f ms, detections per frame %s"
           % (len(times), 1000 * sum(times) / len(times), 1000 * max(times), n_det))
        print("  labels: %s" % ", ".join("%s x%d" % kv for kv in sorted(labels.items())))
        if args.mode == "depth":
            if depth_seen > 0:
                ok("depth_m filled for %d detection(s)" % depth_seen)
            else:
                fail("no detection has depth_m", "point the RealSense at a desk 0.3-4 m away; check depth_min/depth_max")
        elif args.mode == "nodepth":
            if depth_seen == 0:
                ok("depth_m is null in nodepth mode")
            else:
                fail("depth_m present in nodepth mode", "camera_mode in the config should be nodepth")
        if max(times) > 3.0:
            fail("a /detect_embed call took over 3 s", "observer runs at 1-2 Hz; try --detector detectnet, FP16")

    try:
        out, dt = call(url, "/embed_text", {"text": args.query})
        if len(out.get("embedding", [])) == 512:
            ok("/embed_text %.0f ms" % (1000 * dt))
        else:
            fail("/embed_text returned %d floats" % len(out.get("embedding", [])))
    except Exception as e:  # noqa: BLE001
        fail("POST /embed_text: %s" % e)

    try:
        out, dt = call(url, "/verify", {"text": args.query})
        ok("/verify %r: found=%s prob=%.2f box=%s (%.0f ms)"
           % (args.query, out.get("found"), float(out.get("prob", 0.0)), out.get("box"), 1000 * dt))
    except Exception as e:  # noqa: BLE001
        fail("POST /verify: %s" % e)

    return 1 if N_FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
