"""Ask the robot from the laptop: laptop mic -> Whisper (on the laptop) -> /query on the Jetson.

Why on the laptop: the Jetson has no room for Whisper next to the vision worker
(CLIP + NanoOWL + D455 about 4.2 GB) and ROS (measured 2026-11-24).

Usage (double-click 음성질문.cmd, or):
  .venv\\Scripts\\python ask_robot.py               Enter = speak, or type a question + Enter
  .venv\\Scripts\\python ask_robot.py --dry-run     only print what Whisper heard
  .venv\\Scripts\\python ask_robot.py --list-mics   show microphones; then --mic <number>

The text goes to the Jetson over SSH (key login) as
  ros2 topic pub --once /query std_msgs/msg/String "{data: ...}"
which is the same topic the ask pane of start_all.sh uses.
"""
import argparse
import json
import os
import queue
import shutil
import subprocess
import sys
import time

import numpy as np

SAMPLE_RATE = 16000
HERE = os.path.dirname(os.path.abspath(__file__))
# Words the demo uses: Whisper spells short object names better with a hint.
DEFAULT_HINT = ("Questions to a robot: Where is the banana? Where is my backpack? Where is the laptop? "
                "Where is the water bottle? Where is the cup? Where is the box? Where is the umbrella?")


def use_lab_ca(ca_path):
    """The lab Wi-Fi (rcv-robot) inspects TLS. Python's requests uses certifi, not
    the Windows store, so the model download fails there. Append the lab CA."""
    if not ca_path or not os.path.isfile(ca_path):
        return
    try:
        import certifi
    except ImportError:
        print("  [WARN] certifi is missing, so the lab CA is not used: pip install certifi", flush=True)
        return
    bundle = os.path.join(HERE, ".venv", "ca_bundle_with_lab.pem")
    if not os.path.isfile(bundle):
        with open(certifi.where(), "rb") as f:
            base = f.read()
        with open(ca_path, "rb") as f:
            lab = f.read()
        with open(bundle, "wb") as f:
            f.write(base + b"\n" + lab)
    # Assign, not setdefault: another tool (conda) may already have set SSL_CERT_FILE
    # to a bundle that lacks the lab CA (seen on 2026-11-24).
    os.environ["REQUESTS_CA_BUNDLE"] = bundle
    os.environ["SSL_CERT_FILE"] = bundle
    # The Xet downloader (hf_xet, Rust) ignores these variables and fails behind the
    # lab proxy; the plain HTTPS download honours them.
    os.environ.setdefault("HF_HUB_DISABLE_XET", "1")


def record(mic, max_seconds, silence_rms, silence_after):
    """Record until `silence_after` seconds of quiet after speech, or max_seconds."""
    import sounddevice as sd
    q = queue.Queue()
    block = int(SAMPLE_RATE * 0.1)

    def cb(indata, frames, t, status):
        q.put(indata[:, 0].copy())

    chunks, spoke, quiet, peak = [], False, 0.0, 0.0
    t0 = time.time()
    with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="float32", blocksize=block,
                        device=mic, callback=cb):
        while time.time() - t0 < max_seconds:
            try:
                x = q.get(timeout=1.0)
            except queue.Empty:
                continue
            chunks.append(x)
            rms = float(np.sqrt(np.mean(x * x)))
            peak = max(peak, rms)
            bar = "#" * min(40, int(rms * 200))
            sys.stdout.write("\r  loudness %-40s" % bar)
            sys.stdout.flush()
            if rms >= silence_rms:
                spoke, quiet = True, 0.0
            elif spoke:
                quiet += len(x) / SAMPLE_RATE
                if quiet >= silence_after:
                    break
    sys.stdout.write("\r" + " " * 60 + "\r")
    audio = np.concatenate(chunks) if chunks else np.zeros(0, np.float32)
    return audio, spoke, peak


def publish(text, host, topic, dry_run):
    """Publish one std_msgs/String on the Jetson through SSH. True on success."""
    if dry_run:
        return True
    quoted = "'" + text.replace("'", "'\"'\"'") + "'"  # single-quote for bash
    # A small rclpy publisher instead of `ros2 topic pub --once`: it waits until the
    # finder is subscribed, then publishes once. About 6 s faster, and it says so when
    # nobody listens (measured 2026-11-24: 11.8 s with the CLI, about 5 s this way).
    script = ("source ~/object-finder-bot/robot/env.sh >/dev/null 2>&1\n"
              "/usr/bin/python3 - %s %s <<'PY'\n"
              "import sys, time, rclpy\n"
              "from std_msgs.msg import String\n"
              "rclpy.init(); n = rclpy.create_node('ask_robot_pub')\n"
              "p = n.create_publisher(String, sys.argv[1], 10)\n"
              "t = time.time()\n"
              "while p.get_subscription_count() == 0 and time.time() - t < 8: time.sleep(0.1)\n"
              "subs = p.get_subscription_count()\n"
              "p.publish(String(data=sys.argv[2])); rclpy.spin_once(n, timeout_sec=0.3)\n"
              "print('PUB_OK' if subs else 'NO_SUBSCRIBER')\n"
              "PY\n" % (topic, quoted))
    ssh = shutil.which("ssh") or "ssh"
    try:
        r = subprocess.run([ssh, "-o", "BatchMode=yes", "-o", "ConnectTimeout=5", host, "bash -s"],
                           input=script.encode("utf-8"), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           timeout=40)
    except subprocess.TimeoutExpired:
        print("  [FAIL] SSH timed out: is the Jetson on and on the same Wi-Fi?")
        return False
    out = r.stdout.decode("utf-8", "replace")
    if "PUB_OK" in out:
        return True
    if "NO_SUBSCRIBER" in out:
        print("  [FAIL] nobody listens on %s: is start_all.sh (the objmem nodes) running on the Jetson?" % topic)
        return False
    err ="\n".join(l for l in r.stderr.decode("utf-8", "replace").splitlines()
                    if "post-quantum" not in l and "store now" not in l and "upgraded" not in l)
    print("  [FAIL] could not publish (exit %d): %s" % (r.returncode, (err or out).strip()[-300:]))
    return False


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", default="device06@192.168.1.206", help="Jetson user@ip (SSH key login)")
    ap.add_argument("--topic", default="/query")
    ap.add_argument("--model", default="base.en", help="tiny.en (fastest), base.en, small.en (best, slower)")
    ap.add_argument("--mic", type=int, default=None, help="microphone number from --list-mics")
    ap.add_argument("--list-mics", action="store_true")
    ap.add_argument("--hint", default=DEFAULT_HINT, help="words Whisper should expect ('' for none)")
    ap.add_argument("--silence-rms", type=float, default=0.02, help="raise in a noisy room")
    ap.add_argument("--max-seconds", type=float, default=7.0)
    ap.add_argument("--dry-run", action="store_true", help="print the text, do not send it")
    ap.add_argument("--ca", default=os.path.join(os.path.expanduser("~"), "lab-ca.pem"),
                    help="lab Wi-Fi CA certificate for the first model download")
    args = ap.parse_args()

    if args.list_mics:
        import sounddevice as sd
        print(sd.query_devices())
        return 0

    use_lab_ca(args.ca)
    from faster_whisper import WhisperModel
    print("Loading Whisper %s on the laptop CPU (first time downloads it)..." % args.model, flush=True)
    t = time.time()
    model = WhisperModel(args.model, device="cpu", compute_type="int8")
    print("ready in %.1f s. Robot: %s, topic %s%s" % (time.time() - t, args.host, args.topic,
                                                      " (dry run)" if args.dry_run else ""))
    print("Say e.g. 'Where is the banana?'. You can also type the question instead.")

    while True:
        try:
            line = input("\n[Enter] speak / type a question / q quit > ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if line.lower() in ("q", "quit", "exit"):
            break
        if line:
            text = line
        else:
            print("  listening... (stops 1 s after you stop talking)")
            audio, spoke, peak = record(args.mic, args.max_seconds, args.silence_rms, 1.0)
            if not spoke:
                print("  heard nothing (loudest %.3f < %.3f). Speak closer, or --silence-rms %.3f"
                      % (peak, args.silence_rms, max(0.005, peak * 0.6)))
                continue
            t = time.time()
            segs, _ = model.transcribe(audio, language="en", beam_size=5,
                                       initial_prompt=args.hint or None, condition_on_previous_text=False)
            text = " ".join(s.text.strip() for s in segs).strip().strip('"').strip()
            print("  heard: %r (%.1f s)" % (text, time.time() - t))
            if not text:
                continue
        if publish(text, args.host, args.topic, args.dry_run):
            print("  [OK] %s %r" % ("would send" if args.dry_run else "sent to " + args.topic, text))
    return 0


if __name__ == "__main__":
    sys.exit(main())
