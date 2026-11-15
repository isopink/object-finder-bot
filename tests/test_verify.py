import math

import numpy as np

from objmem.embed import FakeEmbedder
from objmem.fakes import FakeCamera, FakeDetector
from objmem.types import Params
from objmem.verify import check_frame, live_scores, prompt_list, softmax_probs


class TableEmbedder:
    def __init__(self, table):
        self.table = {k: np.asarray(v, np.float32) for k, v in table.items()}

    def embed_text(self, text):
        return self.table[text]

    def embed_images(self, images):
        raise AssertionError("not used")


def test_prompts_contained_in_query_are_dropped():
    bg = ["a photo of a wall", "a photo of a desk", "a photo of a chair"]
    assert prompt_list("a photo of a desk lamp", bg) == ["a photo of a desk lamp", "a photo of a wall", "a photo of a chair"]
    assert prompt_list("A Photo of a Wall clock", bg)[1:] == ["a photo of a desk", "a photo of a chair"]


def test_softmax_hand_computed():
    params = Params(background_prompts=["a photo of a wall", "a photo of a desk"], clip_logit_scale=10.0)
    emb = TableEmbedder({"a red mug": [1, 0, 0], "a photo of a wall": [0, 1, 0], "a photo of a desk": [0, 0, 1]})
    vecs = np.array([[0.6, 0.8, 0.0], [1.0, 0.0, 0.0]])
    probs, sims = live_scores(vecs, "a red mug", emb, params)
    # window 0: logits 6, 8, 0
    e6, e8 = math.exp(6), math.exp(8)
    assert abs(probs[0] - e6 / (e6 + e8 + 1)) < 1e-6  # float32 vectors
    # window 1: logits 10, 0, 0
    assert abs(probs[1] - math.exp(10) / (math.exp(10) + 2)) < 1e-6
    assert np.allclose(sims, [0.6, 1.0])


def test_softmax_scale_100_default():
    p = softmax_probs(np.array([[0.8, 0.6]]), np.array([[1.0, 0.0], [0.0, 1.0]]), 100.0)
    assert abs(p[0, 0] - 1.0 / (1.0 + math.exp(-20))) < 1e-12
    assert abs(p.sum() - 1) < 1e-12


def test_check_frame_finds_colored_object_both_modes():
    params = Params()
    e = FakeEmbedder()
    for mode in ("depth", "nodepth"):
        f = FakeCamera(mode=mode).read()
        boxes = FakeDetector().detect(f.color)
        found, prob, box = check_frame(f.color, boxes, "a red mug", e, params)
        assert found and prob >= params.found_thresh
        l, t, r, b = box
        cx, cy = (l + r) / 2, (t + b) / 2
        assert 64 < cx < 220 and 160 < cy < 360  # on the red cup (frac 0.15-0.30, 0.40-0.70)
        found, prob, box = check_frame(f.color, boxes, "a green plant", e, params)
        assert not found and box is None and prob < params.found_thresh


def test_check_frame_without_boxes_uses_windows():
    f = FakeCamera().read()
    found, prob, _ = check_frame(f.color, None, "a blue book", FakeEmbedder(), Params())
    assert found


def test_threshold_applies():
    f = FakeCamera().read()
    found, prob, _ = check_frame(f.color, [], "a red mug", FakeEmbedder(), Params(found_thresh=1.01))
    assert not found and prob > 0.5
