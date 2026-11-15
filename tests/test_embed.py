import sys

import numpy as np
import pytest

from objmem.embed import CachedTextEmbedder, ClipEmbedder, FakeEmbedder
from objmem.fakes import FakeCamera


def test_import_does_not_load_torch():
    import objmem.embed  # noqa: F401
    assert "open_clip" not in sys.modules


def test_fake_text_is_deterministic_and_normalized():
    e = FakeEmbedder()
    a, b = e.embed_text("a red mug"), FakeEmbedder().embed_text("a red mug")
    assert a.shape == (512,) and a.dtype == np.float32
    assert np.allclose(a, b)
    assert abs(np.linalg.norm(a) - 1) < 1e-5


def test_fake_image_matches_its_color():
    e = FakeEmbedder()
    red = np.zeros((40, 40, 3), np.uint8)
    red[:] = (220, 30, 30)
    gray = np.full((40, 40, 3), 128, np.uint8)
    v = e.embed_images([red, gray])
    assert v.shape == (2, 512)
    assert np.allclose(np.linalg.norm(v, axis=1), 1, atol=1e-5)
    assert v[0] @ e.embed_text("a red mug") > 0.7
    assert abs(v[0] @ e.embed_text("a green plant")) < 0.3
    assert v[1] @ e.embed_text("a photo of a wall") > 0.6
    assert e.embed_images([]).shape == (0, 512)


def test_fake_same_object_two_frames_close():
    e = FakeEmbedder()
    cam = FakeCamera()
    c1 = cam.read().color[200:330, 100:190]
    c2 = cam.read().color[195:340, 95:200]
    v = e.embed_images([c1, c2])
    assert v[0] @ v[1] > 0.95


def test_cache_calls_inner_once():
    class Counting(FakeEmbedder):
        n = 0

        def embed_text(self, text):
            Counting.n += 1
            return FakeEmbedder.embed_text(self, text)

    c = CachedTextEmbedder(Counting(), maxsize=2)
    a = c.embed_text("x")
    c.embed_text("x")
    assert Counting.n == 1 and c.hits == 1
    c.embed_text("y")
    c.embed_text("z")  # evicts x
    c.embed_text("x")
    assert Counting.n == 4
    assert np.allclose(a, c.embed_text("x"))


def test_clip_embedder_needs_open_clip():
    try:
        import open_clip  # noqa: F401
        import torch  # noqa: F401
    except ImportError:
        with pytest.raises(ImportError):
            ClipEmbedder()
    else:
        pytest.skip("open_clip installed; real model not loaded in unit tests")
