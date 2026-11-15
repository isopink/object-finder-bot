"""Terminal front end: type queries, watch /objmem/status.

    ros2 run objmem_ros ask            # q <text> to search
    ros2 run objmem_ros ask --voice    # also: v to speak a query (Whisper)

Commands: q <text>  search; v  speak one query (--voice); c  cancel the
current goal; h  help; exit  quit.
"""
import argparse
import sys
import threading

HELP = """commands:
  q <text>   search, e.g.  q where is the blue mug
  v          speak one query (needs --voice)
  c          cancel the current navigation goal
  h          this help
  exit       quit"""


def parse_command(line, voice=False):
    """-> (action, text). action in query | voice | cancel | help | exit | empty | unknown."""
    s = line.strip()
    if not s:
        return "empty", ""
    head, _, rest = s.partition(" ")
    head = head.lower()
    if head == "q":
        return ("query", rest.strip()) if rest.strip() else ("unknown", s)
    if head == "v":
        return ("voice", "") if voice else ("unknown", s)
    if head == "c":
        return "cancel", ""
    if head in ("h", "help", "?"):
        return "help", ""
    if head in ("exit", "quit"):
        return "exit", ""
    return "unknown", s


def main(argv=None):
    import rclpy
    from rclpy.node import Node
    from std_msgs.msg import String

    argv = sys.argv[1:] if argv is None else argv
    ap = argparse.ArgumentParser(prog="ask")
    ap.add_argument("--voice", action="store_true", help="enable the v command (Whisper speech to text)")
    ap.add_argument("--config", default="", help="YAML with Params keys (whisper_model, mic_device)")
    ap.add_argument("--whisper-model", default=None, help="default: whisper_model in the config (base.en)")
    ap.add_argument("--mic", default=None, help="ALSA device, e.g. plughw:2,0; default: mic_device in the config")
    args, ros_args = ap.parse_known_args(argv)

    rclpy.init(args=[sys.argv[0]] + ros_args)
    node = Node("objmem_ask")
    pub = node.create_publisher(String, "/query", 10)
    cancel_pub = node.create_publisher(String, "/objmem/cancel", 10)
    node.create_subscription(String, "/objmem/status", lambda m: print("  [status] " + m.data, flush=True), 10)
    stt = None
    if args.voice:
        from objmem.speech import WhisperSTT
        from objmem.types import Params
        params = Params.load(args.config or None)
        stt = WhisperSTT(model=args.whisper_model or params.whisper_model,
                         mic=(args.mic or params.mic_device) or None)

    spinner = threading.Thread(target=rclpy.spin, args=(node,), daemon=True)
    spinner.start()
    print(HELP, flush=True)

    def publish(text):
        msg = String()
        msg.data = text
        pub.publish(msg)
        print("  sent: " + text, flush=True)

    try:
        while True:
            try:
                line = input("> ")
            except EOFError:
                break
            action, text = parse_command(line, voice=args.voice)
            if action == "query":
                publish(text)
            elif action == "voice":
                print("  listening...", flush=True)
                try:
                    heard = stt.listen().strip()
                except Exception as exc:
                    print("  speech failed: {}".format(exc), flush=True)
                    continue
                print("  heard: {!r}".format(heard), flush=True)
                if heard:
                    publish(heard)
            elif action == "cancel":
                cancel_pub.publish(String())
            elif action == "help":
                print(HELP, flush=True)
            elif action == "exit":
                break
            elif action == "unknown":
                print("  unknown command; h for help", flush=True)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        try:
            rclpy.shutdown()
        except Exception:
            pass


if __name__ == "__main__":
    main()
