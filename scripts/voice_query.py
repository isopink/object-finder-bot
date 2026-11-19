"""Spoken queries: microphone -> Whisper -> /query (the same topic the ask pane uses).

Why a separate program: the ask pane (start_all.sh) runs in the ROS Python
without conda, where Whisper has no CUDA PyTorch. This script runs in the conda
env (like the vision worker), turns one utterance into English text with
objmem.speech.WhisperSTT, and hands the text to ROS with
`ros2 topic pub --once /query std_msgs/msg/String`.

Run it with robot/voice.sh (sources ROS, activates conda):
  ./robot/voice.sh                     # Enter = speak one query, q = quit
  ./robot/voice.sh --dry-run           # print the text, do not publish
  ./robot/voice.sh --mic plughw:2,0    # ALSA capture device from `arecord -l`

Python 3.8 syntax (Jetson).
"""
import argparse
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(os.path.dirname(HERE), "src")
if os.path.isdir(SRC) and SRC not in sys.path:
    sys.path.insert(0, SRC)

from objmem.speech import WhisperSTT  # noqa: E402
from objmem.types import Params  # noqa: E402


def publish_query(text, topic="/query", timeout=15):
    """Publish one std_msgs/String on topic with the ros2 CLI; True on success."""
    # JSON string literals are valid YAML, so quotes and colons in the text are safe.
    msg = "{data: %s}" % json.dumps(text)
    cmd = ["ros2", "topic", "pub", "--once", topic, "std_msgs/msg/String", msg]
    try:
        r = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=timeout)
    except FileNotFoundError:
        print("  [FAIL] ros2 not found: run this through ./robot/voice.sh", flush=True)
        return False
    except subprocess.TimeoutExpired:
        print("  [FAIL] ros2 topic pub timed out (are the objmem nodes running?)", flush=True)
        return False
    if r.returncode != 0:
        print("  [FAIL] ros2 topic pub: %s" % r.stderr.decode("utf-8", "replace").strip(), flush=True)
        return False
    return True


def clean(text):
    """Whisper output -> query text: trimmed, no surrounding quotes."""
    return text.strip().strip('"').strip()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default=None, help="YAML with whisper_model and mic_device")
    ap.add_argument("--model", default=None, help="Whisper model (default: whisper_model in the config, base.en)")
    ap.add_argument("--mic", default=None, help="ALSA capture device, e.g. plughw:2,0 (default: mic_device in the config)")
    ap.add_argument("--silence-rms", type=float, default=0.015,
                    help="loudness below which a chunk counts as silence; raise it in a noisy room")
    ap.add_argument("--max-seconds", type=float, default=8.0)
    ap.add_argument("--device", default=None, help="cuda or cpu (default: Whisper decides)")
    ap.add_argument("--topic", default="/query")
    ap.add_argument("--dry-run", action="store_true", help="print the recognized text only")
    ap.add_argument("--once", action="store_true", help="one utterance, then exit")
    args = ap.parse_args()

    params = Params.load(args.config)
    model = args.model or getattr(params, "whisper_model", "") or "base.en"
    mic = args.mic or getattr(params, "mic_device", "") or None
    stt = WhisperSTT(model=model, device=args.device, max_seconds=args.max_seconds,
                     silence_rms=args.silence_rms, mic=mic)
    print("voice queries: model %s, mic %s, topic %s%s"
          % (model, mic or "ALSA default", args.topic, " (dry run)" if args.dry_run else ""), flush=True)
    print("Speak English, e.g. 'Where is the blue mug?'. The first query loads Whisper (slow).", flush=True)

    while True:
        if not args.once:
            try:
                line = input("\n[Enter] speak, [q] quit > ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if line in ("q", "quit", "exit"):
                break
        print("  listening... (stops 1 s after you stop talking)", flush=True)
        t0 = time.time()
        try:
            text = clean(stt.listen())
        except Exception as exc:  # noqa: BLE001
            print("  [FAIL] speech: %s" % exc, flush=True)
            text = ""
        dt = time.time() - t0
        if not text:
            print("  heard nothing (%.1f s). Speak louder, move the mic closer, or lower --silence-rms." % dt,
                  flush=True)
        else:
            print("  heard: %r (%.1f s)" % (text, dt), flush=True)
            if not args.dry_run:
                if publish_query(text, args.topic):
                    print("  [OK] sent to %s; watch the ask pane or the map view" % args.topic, flush=True)
        if args.once:
            break
    stt.unload()
    return 0


if __name__ == "__main__":
    sys.exit(main())
