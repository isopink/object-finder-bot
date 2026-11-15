import numpy as np

from objmem.crops import detection_crops, grid_crops, sliding_crops
from objmem.types import RawBox


def frame(w, h):
    return np.zeros((h, w, 3), dtype=np.uint8)


def test_sliding_83_windows_on_1080p():
    crops = sliding_crops(frame(1920, 1080))
    assert len(crops) == 83
    labels = [c.label for c in crops]
    assert labels.count("win2") == 9 and labels.count("win3") == 25 and labels.count("win4") == 49
    for c in crops:
        l, t, r, b = c.box
        assert 0 <= l < r <= 1920 and 0 <= t < b <= 1080
        assert c.image.shape == (b - t, r - l, 3)


def test_sliding_half_window_sizes_and_overlap():
    crops = [c for c in sliding_crops(frame(1920, 1080)) if c.label == "win2"]
    assert crops[0].box == (0, 0, 960, 540)
    assert crops[1].box == (480, 0, 1440, 540)  # 50% overlap
    assert crops[-1].box == (960, 540, 1920, 1080)


def test_grid_3x3():
    crops = grid_crops(frame(640, 480))
    assert len(crops) == 9
    assert crops[0].box == (0, 0, 213, 160)
    assert crops[4].label == "tile11"
    assert crops[8].box == (426, 320, 640, 480)
    assert crops[8].label == "tile22"


def test_detection_padding_and_clip_at_borders():
    f = frame(640, 480)
    crops = detection_crops(f, [RawBox((100, 100, 200, 300), "cup", 0.9)], pad=0.1)
    assert crops[0].box == (90, 80, 210, 320)
    assert crops[0].label == "cup"
    # box at the corner: padding clipped to the frame
    crops = detection_crops(f, [RawBox((0, 0, 50, 40), "a", 0.9), RawBox((600, 450, 640, 480), "b", 0.9)])
    assert crops[0].box == (0, 0, 55, 44)
    assert crops[1].box == (596, 447, 640, 480)


def test_detection_skips_small_crops_and_accepts_tuples():
    f = frame(640, 480)
    crops = detection_crops(f, [((10, 10, 18, 100), "thin", 0.5), (50, 50, 150, 150)], pad=0.1)
    assert len(crops) == 1
    assert crops[0].label == "object"


def test_crop_is_a_copy():
    f = frame(64, 64)
    c = grid_crops(f)[0]
    c.image[:] = 255
    assert f.max() == 0
