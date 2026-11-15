import threading

import numpy as np
import pytest

from objmem.embed import FakeEmbedder
from objmem.fakes import DEFAULT_OBJECTS, FakeCamera, FakeDetector
from objmem.types import Detection, Params
from objmem.worker import ClientEmbedder, ClientVerifier, VisionClient, VisionWorkerError, make_server


@pytest.fixture
def start():
    servers = []

    def _start(mode="depth", camera=True, detector=None):
        params = Params(camera_mode=mode)
        cam = FakeCamera(mode=mode, size=(params.img_w, params.img_h), clock=lambda: 123.0) if camera else None
        srv = make_server(FakeEmbedder(), detector or FakeDetector(), cam, params, host="127.0.0.1", port=0)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        servers.append(srv)
        return VisionClient("http://127.0.0.1:{}".format(srv.server_address[1]), timeout=10.0), srv

    yield _start
    for s in servers:
        s.shutdown()
        s.server_close()


@pytest.mark.parametrize("mode", ["depth", "nodepth"])
def test_health(start, mode):
    client, _ = start(mode)
    assert client.health() == {"ok": True, "camera": True, "camera_mode": mode}
    client2, _ = start(mode, camera=False)
    assert client2.health()["camera"] is False


@pytest.mark.parametrize("mode", ["depth", "nodepth"])
def test_detect_embed_camera(start, mode):
    client, _ = start(mode)
    dets = client.detect_embed()
    assert client.last_t == 123.0
    assert [d.label for d in dets] == [o.label for o in DEFAULT_OBJECTS]
    for d, o in zip(dets, DEFAULT_OBJECTS):
        assert isinstance(d, Detection)
        assert d.embedding.shape == (512,) and d.embedding.dtype == np.float32
        assert abs(np.linalg.norm(d.embedding) - 1) < 1e-4
        if mode == "depth":
            assert d.depth_m == pytest.approx(o.depth_m)
        else:
            assert d.depth_m is None
    assert dets[0].box == (96, 192, 192, 336)  # detector box, not the padded crop


@pytest.mark.parametrize("mode", ["depth", "nodepth"])
def test_detect_embed_sent_image(start, mode):
    client, _ = start(mode, camera=False)
    color = FakeCamera(mode).read().color
    dets = client.detect_embed(color)
    assert len(dets) == 2 and all(d.depth_m is None for d in dets)
    e = FakeEmbedder()
    assert dets[0].embedding @ e.embed_text("a red cup") > 0.7
    assert dets[1].embedding @ e.embed_text("a blue book") > 0.7


def test_detect_embed_tiles_when_nothing_detected(start):
    client, _ = start("depth", detector=FakeDetector(boxes=[]))
    dets = client.detect_embed()
    assert [d.label for d in dets] == ["tile{}{}".format(r, c) for r in range(3) for c in range(3)]
    assert all(d.conf == 0.0 and d.depth_m is not None for d in dets)


@pytest.mark.parametrize("mode", ["depth", "nodepth"])
def test_verify_both_image_modes(start, mode):
    client, _ = start(mode)
    found, prob = client.verify("a red mug")
    assert found and prob > 0.5
    found, prob, box = client.verify_full("a green plant")
    assert not found and box is None
    color = FakeCamera(mode).read().color
    found, prob, box = client.verify_full("a blue book", color)
    assert found and box is not None
    v = ClientVerifier(client)
    assert v.check("a red mug")[0] is True
    assert v.last_box is not None
    assert v.check("a yellow banana")[0] is False


@pytest.mark.parametrize("mode", ["depth", "nodepth"])
def test_embed_text(start, mode):
    client, srv = start(mode)
    a = client.embed_text("a red mug")
    assert np.allclose(a, FakeEmbedder().embed_text("a red mug"), atol=1e-6)
    client.embed_text("a red mug")
    assert srv.service.embedder.hits >= 1  # cached
    assert np.allclose(ClientEmbedder(client).embed_text("a red mug"), a)


def test_errors(start):
    client, _ = start("depth", camera=False)
    with pytest.raises(VisionWorkerError, match="503"):
        client.detect_embed()
    with pytest.raises(VisionWorkerError, match="400"):
        client.verify("")
    with pytest.raises(VisionWorkerError, match="404"):
        client._call("GET", "/nope")
    with pytest.raises(VisionWorkerError, match="400"):
        client._call("POST", "/detect_embed", {"image_jpeg_b64": "notajpeg"})
    assert client.health()["ok"]  # still serving


def test_camera_without_frame(start):
    client, srv = start("depth")
    srv.service.camera.available = False
    with pytest.raises(VisionWorkerError, match="no frame"):
        client.verify("a red mug")


def test_unreachable():
    with pytest.raises(VisionWorkerError, match="cannot reach"):
        VisionClient("http://127.0.0.1:1", timeout=1.0).health()
