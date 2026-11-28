import io

import numpy as np
import pytest

from objmem.types import MemoryItem, Pose2D
from objmem.viz import OccupancyGrid, draw_map, load_map, p_color, save_map

PIL = pytest.importorskip("PIL")
from PIL import Image  # noqa: E402

PNG = b"\x89PNG\r\n\x1a\n"


def _item(i, x, y, p, cov=None, label="cup"):
    return MemoryItem(id=i, mu=np.array([x, y]), cov=np.eye(2) * 0.04 if cov is None else cov,
                      embedding=np.zeros(512, dtype=np.float32), p=p, t_last=0.0, n_obs=1,
                      view_pose=Pose2D(x - 1, y, 0.0), label=label)


def _open(png):
    assert png.startswith(PNG)
    return Image.open(io.BytesIO(png)).convert("RGB")


def test_import_does_not_need_pil():
    import objmem.viz as v
    src = open(v.__file__, encoding="utf-8").read()
    head = src.split("def ")[0]
    assert "import PIL" not in head and "from PIL" not in head


def test_empty_map():
    img = _open(draw_map([]))
    assert img.size[0] > 100 and img.size[1] > 100


def test_items_robot_path_truth():
    items = [_item(0, 1.0, 1.0, 0.95), _item(1, 3.0, 2.0, 0.1, label=None),
             _item(2, 2.0, 0.0, 0.5, cov=np.array([[2.0, 1.9], [1.9, 2.0]])),
             _item(3, float("nan"), 0.0, 0.5)]
    png = draw_map(items, robot_pose=Pose2D(2.0, 1.0, 0.5), path=[(0, 0), Pose2D(1, 1, 0), (2, 1)],
                   truth={"blue_mug": (1.0, 1.1), "unknown": (None, None)}, title="t", highlight=0)
    img = np.asarray(_open(png))
    # high-p items are green, low-p red
    greens = np.sum((img[:, :, 1] > 130) & (img[:, :, 0] < 60) & (img[:, :, 2] < 100))
    reds = np.sum((img[:, :, 0] > 200) & (img[:, :, 1] < 70) & (img[:, :, 2] < 70))
    assert greens > 10 and reds > 10


def test_p_color_ramp():
    assert p_color(0.0) == (215, 48, 39)
    assert p_color(1.0) == (26, 150, 65)
    assert p_color(0.5) == (240, 190, 40)
    assert p_color(-3) == p_color(0.0) and p_color(7) == p_color(1.0)


def _write_map(folder, w=40, h=20):
    pix = np.full((h, w), 254, dtype=np.uint8)  # free
    pix[0, :] = 0                                # top row (highest y) occupied
    pix[:, :5] = 205                             # left strip unknown
    Image.fromarray(pix, "L").save(str(folder / "lab.pgm"))
    (folder / "lab.yaml").write_text(
        "image: lab.pgm\nresolution: 0.05\norigin: [-1.0, -0.5, 0.0]\nnegate: 0\n"
        "occupied_thresh: 0.65\nfree_thresh: 0.196\n", encoding="utf-8")
    return str(folder / "lab.yaml")


def test_load_map_saver_files(tmp_path):
    og = load_map(_write_map(tmp_path))
    assert og.grid.shape == (20, 40)
    assert og.resolution == 0.05
    assert og.origin == (-1.0, -0.5)
    assert np.all(og.grid[-1, 5:] == 100)  # image top row -> highest y -> last grid row
    assert np.all(og.grid[0, 5:] == 0)
    assert np.all(og.grid[:, :5] == -1)
    assert og.extent == pytest.approx((-1.0, -0.5, 1.0, 0.5))


def test_draw_with_occupancy_path_and_grid(tmp_path):
    yaml_path = _write_map(tmp_path)
    png1 = draw_map([_item(0, 0.0, 0.0, 0.9)], occupancy=yaml_path)
    og = load_map(yaml_path)
    png2 = draw_map([_item(0, 0.0, 0.0, 0.9)], occupancy=og)
    png3 = draw_map([_item(0, 0.0, 0.0, 0.9)], occupancy=(og.grid, og.resolution, og.origin))
    assert png1 == png2 == png3
    img = np.asarray(_open(png1))
    assert np.sum(np.all(img == 90, axis=2)) > 50  # occupied cells drawn


def test_bad_occupancy_type():
    with pytest.raises(TypeError):
        draw_map([], occupancy=42)


def test_save_map(tmp_path):
    out = save_map(str(tmp_path / "sub" / "m.png"), [_item(0, 1, 1, 0.7)], robot_pose=Pose2D(0, 0, 0))
    assert open(out, "rb").read().startswith(PNG)


def test_toy_world_occupancy():
    from objmem.sim.world import ToyWorld
    og = ToyWorld().occupancy()
    assert isinstance(og, OccupancyGrid)
    assert (og.grid == 100).sum() > 0 and (og.grid == 0).sum() > 0
    assert _open(draw_map([], occupancy=og))


def test_planned_route_is_drawn_in_orange():
    import io as _io
    import numpy as _np
    from PIL import Image
    from objmem.viz import draw_map
    plain = draw_map([], bounds=(-1, -1, 5, 5))
    with_plan = draw_map([], bounds=(-1, -1, 5, 5), plan=[(0, 0), (3, 0), (3, 3)])
    a = _np.asarray(Image.open(_io.BytesIO(plain)).convert("RGB")).astype(int)
    b = _np.asarray(Image.open(_io.BytesIO(with_plan)).convert("RGB")).astype(int)
    orange = (abs(b[..., 0] - 245) < 20) & (abs(b[..., 1] - 130) < 25) & (b[..., 2] < 60)
    before = ((abs(a[..., 0] - 245) < 20) & (abs(a[..., 1] - 130) < 25) & (a[..., 2] < 60)).sum()  # the p colour legend
    assert orange.sum() > before + 1000


def test_path_is_a_blue_line_broken_at_none():
    from PIL import Image
    import io
    bounds = (0.0, 0.0, 4.0, 4.0)
    png = draw_map([], path=[(0.5, 2.0), (1.5, 2.0), None, (2.5, 2.0), (3.5, 2.0)], bounds=bounds, size=440)
    px = np.asarray(Image.open(io.BytesIO(png)).convert("RGB")).astype(int)

    def is_blue(x_m):          # y = 2 m, on the 100 px per meter canvas (left 20, top 28)
        r, g, b = px[28 + 200, 20 + int(x_m * 100)]
        return b > 200 and r < 90
    assert is_blue(0.75) and is_blue(3.25)
    assert not is_blue(2.25)                               # the gap between the two pieces
