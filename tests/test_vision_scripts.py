import json
import os
import socket
import subprocess
import sys
import time
import urllib.request

import numpy as np
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import tune_verify  # noqa: E402


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.mark.parametrize("mode", ["depth", "nodepth"])
def test_vision_worker_fake_starts(tmp_path, mode):
    cfg = tmp_path / "c.yaml"
    cfg.write_text("camera_mode: {}\n".format(mode))
    port = free_port()
    proc = subprocess.Popen([sys.executable, os.path.join(ROOT, "scripts", "vision_worker.py"), "--fake",
                             "--config", str(cfg), "--host", "127.0.0.1", "--port", str(port)],
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    try:
        url = "http://127.0.0.1:{}".format(port)
        deadline = time.time() + 20
        while True:
            try:
                with urllib.request.urlopen(url + "/health", timeout=2) as r:
                    health = json.loads(r.read().decode())
                break
            except OSError:
                if time.time() > deadline or proc.poll() is not None:
                    raise
                time.sleep(0.2)
        assert health == {"ok": True, "camera": True, "camera_mode": mode}
        from objmem.worker import VisionClient
        dets = VisionClient(url).detect_embed()
        assert len(dets) == 2
        assert (dets[0].depth_m is None) == (mode == "nodepth")
    finally:
        proc.terminate()
        proc.wait(10)


def test_object_name_and_queries(tmp_path):
    assert tune_verify.object_name("x/blue_mug_2.jpg") == "blue_mug"
    assert tune_verify.object_name("red_book-10.PNG") == "red_book"
    assert tune_verify.object_name("plant.jpg") == "plant"
    q = tmp_path / "q.yaml"
    q.write_text("blue_mug: a blue mug\nred_book: [a red book, the red book]\n")
    assert tune_verify.parse_queries(['plant="a green plant"', "a cup"], str(q)) == [
        ("blue_mug", "a blue mug"), ("red_book", "a red book"), ("red_book", "the red book"),
        ("plant", "a green plant"), (None, "a cup")]


def test_compute_rates():
    rows = [("a", "a", 0.9), ("a", "a", 0.45), ("b", "a", 0.35), ("b", "b", 0.65), ("a", "b", 0.1), ("a", None, 0.99)]
    r = {x["thresh"]: x for x in tune_verify.compute_rates(rows)}
    assert r[0.3]["hits"] == 3 and r[0.3]["positives"] == 3 and r[0.3]["false_alarms"] == 1
    assert r[0.5]["hit_rate"] == pytest.approx(2 / 3) and r[0.5]["fa_rate"] == 0.0
    assert r[0.7]["hits"] == 1
    assert "| 0.5 |" in tune_verify.format_rates(tune_verify.compute_rates(rows))


def test_tune_verify_fake_run(tmp_path, capsys):
    from PIL import Image
    from objmem.embed import FAKE_COLORS
    for name, color in [("red_mug", "red"), ("red_mug_2", "red"), ("blue_book", "blue")]:
        img = np.full((360, 640, 3), 128, np.uint8)
        img[100:250, 200:350] = FAKE_COLORS[color]
        Image.fromarray(img).save(str(tmp_path / (name + ".png")))
    rows = tune_verify.main(["--photos", str(tmp_path), "--fake",
                             "--query", 'red_mug="a red mug"', "--query", "blue_book=a blue book"])
    out = capsys.readouterr().out
    assert "false-alarm rate" in out
    rates = {x["thresh"]: x for x in tune_verify.compute_rates(rows)}
    assert rates[0.5]["hit_rate"] == 1.0 and rates[0.5]["fa_rate"] == 0.0
