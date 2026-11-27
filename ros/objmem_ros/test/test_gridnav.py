"""gridnav: planner and runner on a simulated robot (no ROS, no hardware)."""
import math

import numpy as np
import pytest

from objmem_ros import gridnav as gn

RES = 0.05
ORIGIN = (-1.0, -5.0)
W, H = 180, 120          # 9 x 6 m


def z_corridor():
    """Occupancy data (0 free, 100 occupied) of a Z shaped aisle 1.4 m wide, like room_l4_nav:
    x 0..3 along y = 0, then down x = 3 from y = 0 to y = -3, then x 3..7 along y = -3."""
    occ = np.full((H, W), 100, np.int8)

    def carve(x0, x1, y0, y1):
        for iy in range(H):
            for ix in range(W):
                x, y = ORIGIN[0] + (ix + 0.5) * RES, ORIGIN[1] + (iy + 0.5) * RES
                if x0 <= x <= x1 and y0 <= y <= y1:
                    occ[iy, ix] = 0
    carve(-0.7, 3.7, -0.7, 0.7)
    carve(2.3, 3.7, -3.7, 0.7)
    carve(2.3, 7.0, -3.7, -2.3)
    return occ


@pytest.fixture(scope="module")
def occ():
    return z_corridor()


def make_grid(occ, radius=0.2):
    return gn.grid_from_occupancy(occ.reshape(-1), W, H, RES, ORIGIN, radius)


class SimIO(object):
    """A robot on the raw map. The command of the previous step is applied (a stopping delay);
    the wheels are 3 % off from what is commanded, so closing the loop on the pose matters."""

    def __init__(self, occ, pose, v_gain=0.97, w_gain=1.03, obstacle=None, cancel_after=None):
        self.occ, self.p = occ, list(pose)
        self.t, self.v_gain, self.w_gain = 0.0, v_gain, w_gain
        self.latest, self.applied = (0.0, 0.0), (0.0, 0.0)
        self.cmds, self.logs, self.obstacle, self.cancel_after = [], [], obstacle, cancel_after
        self.min_obstacle_dist = 9.9

    def pose(self):
        return tuple(self.p)

    def cmd(self, v, w):
        self.latest = (v, w)
        self.cmds.append((v, w))

    def now(self):
        return self.t

    def sleep(self, s):
        v, w = self.applied
        x, y, th = self.p
        self.p = [x + v * self.v_gain * math.cos(th) * s, y + v * self.v_gain * math.sin(th) * s,
                  wrap(th + w * self.w_gain * s)]
        self.applied = self.latest
        self.t += s
        if self.obstacle is not None:
            self.min_obstacle_dist = min(self.min_obstacle_dist, math.hypot(self.p[0] - self.obstacle[0], self.p[1] - self.obstacle[1]) - self.obstacle[2])

    def cancelled(self):
        return self.cancel_after is not None and self.t > self.cancel_after

    def log(self, text):
        self.logs.append(text)

    def front(self):
        x, y, th = self.p
        for i in range(1, 400):
            d = i * 0.02
            px, py = x + d * math.cos(th), y + d * math.sin(th)
            ix, iy = int((px - ORIGIN[0]) / RES), int((py - ORIGIN[1]) / RES)
            if not (0 <= ix < W and 0 <= iy < H) or self.occ[iy, ix] != 0:
                return d
            if self.obstacle is not None and math.hypot(px - self.obstacle[0], py - self.obstacle[1]) <= self.obstacle[2]:
                return d
        return 9.9


def wrap(a):
    return (a + math.pi) % (2 * math.pi) - math.pi


def only_four_commands(cmds, speed, turn):
    for v, w in cmds:
        straight = v > 0 and w == 0 and v <= speed + 1e-9
        turning = v == 0 and abs(abs(w) - turn) < 1e-9
        stopped = v == 0 and w == 0
        if not (straight or turning or stopped):
            return False
    return True


# ---------------------------------------------------------------- grid
def test_unknown_and_walls_are_blocked_and_the_robot_radius_is_kept(occ):
    g = make_grid(occ, radius=0.2)
    assert g.is_free(*g.cell(0.0, 0.0))                 # middle of the aisle
    assert not g.is_free(*g.cell(0.0, 0.66))            # 4 cm from the aisle wall: inside the robot radius
    assert g.is_free(*g.cell(0.0, 0.45))                # 0.25 m from the wall
    assert not g.is_free(*g.cell(0.0, 3.0))             # solid
    data = occ.reshape(-1).copy()
    data[:] = -1                                        # unknown everywhere
    assert not make_grid(data.reshape(H, W)).free.any()


# ---------------------------------------------------------------- planner
def test_plan_follows_the_z_with_two_turns(occ):
    g = make_grid(occ)
    segs, used = gn.plan(g, (0.0, 0.0), 0, (6.0, -3.0))
    assert [k for k, _x, _y in segs] == [0, 3, 0]       # +x, then -y, then +x
    assert used == pytest.approx((6.0, -3.0), abs=0.06)
    assert segs[0][2] == pytest.approx(segs[0][2])      # runs are axis aligned:
    (k0, x0, y0), (k1, x1, y1), (k2, x2, y2) = segs
    assert y0 == pytest.approx(0.0, abs=0.06) and x1 == pytest.approx(x0) and y2 == pytest.approx(y1)


def test_plan_no_path_and_goal_snapping(occ):
    g = make_grid(occ)
    assert gn.plan(g, (0.0, 0.0), 0, (0.0, 3.0))[0] is None            # far inside the wall
    segs, used = gn.plan(g, (0.0, 0.0), 0, (6.0, -3.55))               # 0.45 m beyond the aisle edge: snapped in
    assert segs is not None and used[1] > -3.55


def test_plan_start_on_the_edge_still_plans(occ):
    g = make_grid(occ)
    segs, _ = gn.plan(g, (0.0, 0.66), 0, (3.0, -2.0))                  # start inside the grown wall
    assert segs is not None


def test_robot_next_to_the_wall_leaves_it_first_and_arrives(occ):
    wide = lambda: make_grid(occ, radius=0.45)          # a wide robot radius: free only within 0.25 m of the centre line
    io = SimIO(occ, (1.0, 0.55, 0.0))                   # 0.30 m outside that free band, 15 cm from the wall
    r = gn.Runner(io, wide)
    assert r.go((3.0, -2.0)) == "ok"
    assert math.hypot(io.p[0] - 3.0, io.p[1] + 2.0) < 0.25
    assert only_four_commands(io.cmds, r.speed, r.turn_rate)


# ---------------------------------------------------------------- runner
def runner(io, occ, **kw):
    return gn.Runner(io, lambda: make_grid(occ), **kw)


def test_reaches_the_goal_with_four_commands_only(occ):
    io = SimIO(occ, (0.0, 0.0, 0.0))
    r = runner(io, occ)
    assert r.go((6.0, -3.0), goal_yaw=0.0) == "ok"
    x, y, th = io.p
    assert math.hypot(x - 6.0, y + 3.0) < 0.2 and abs(wrap(th)) < math.radians(3)
    assert only_four_commands(io.cmds, r.speed, r.turn_rate)
    assert io.t < 170.0


def test_starts_off_axis_and_turns_to_the_goal_heading(occ):
    io = SimIO(occ, (0.1, 0.05, 0.3))                   # 17 degrees off the axis
    r = runner(io, occ)
    assert r.go((3.0, -2.0), goal_yaw=-math.pi / 2) == "ok"
    x, y, th = io.p
    assert math.hypot(x - 3.0, y + 2.0) < 0.2 and abs(wrap(th + math.pi / 2)) < math.radians(3)
    assert only_four_commands(io.cmds, r.speed, r.turn_rate)


def test_turns_around_in_two_quarter_turns(occ):
    io = SimIO(occ, (3.0, -2.0, -math.pi / 2))          # facing -y, goal is behind (+y)
    r = runner(io, occ)
    assert r.go((3.0, 0.0), goal_yaw=None) == "ok"
    assert math.hypot(io.p[0] - 3.0, io.p[1] - 0.0) < 0.2
    assert only_four_commands(io.cmds, r.speed, r.turn_rate)


def test_no_path(occ):
    io = SimIO(occ, (0.0, 0.0, 0.0))
    assert runner(io, occ).go((0.0, 3.0)) == "no_path"
    assert io.cmds == []                                # never moved


def test_something_in_the_way_stops_the_robot(occ):
    obstacle = (3.0, -1.5, 0.12)                        # a person standing in the vertical aisle
    io = SimIO(occ, (0.0, 0.0, 0.0), obstacle=obstacle)
    r = runner(io, occ, blocked_wait_s=2.0, max_replans=2)
    assert r.go((6.0, -3.0)) in ("blocked", "timeout")
    assert io.min_obstacle_dist > 0.15                  # stopped before touching it
    assert io.cmds[-1] == (0.0, 0.0)


def test_cancel_stops(occ):
    io = SimIO(occ, (0.0, 0.0, 0.0), cancel_after=4.0)
    assert runner(io, occ).go((6.0, -3.0)) == "cancel"
    assert io.cmds[-1] == (0.0, 0.0)


def test_lost_pose_stops(occ):
    io = SimIO(occ, (0.0, 0.0, 0.0))
    seen = {"n": 0}
    real = io.pose

    def flaky():
        seen["n"] += 1
        return real() if seen["n"] < 60 else None
    io.pose = flaky
    assert runner(io, occ).go((6.0, -3.0)) == "lost"
    assert io.cmds[-1] == (0.0, 0.0)


def test_frozen_odometry_stops_instead_of_driving_blind(occ):
    # 2026-11-27: /odom kept publishing the same pose while the wheels turned.
    io = SimIO(occ, (0.0, 0.0, 0.0))
    io.pose = lambda: (0.0, 0.0, 0.0)                   # the robot moves, the reported pose does not
    r = runner(io, occ)
    assert r.go((6.0, -3.0)) == "stuck"
    assert io.cmds[-1] == (0.0, 0.0)
    assert io.t < 5.0                                   # gave up after about 3 s, about 25 cm
    assert math.hypot(io.p[0], io.p[1]) < 0.4


def test_frozen_heading_stops_the_turn(occ):
    io = SimIO(occ, (3.0, -2.0, -math.pi / 2))
    io.pose = lambda: (3.0, -2.0, -math.pi / 2)         # asked to turn around, heading never changes
    r = runner(io, occ)
    assert r.go((3.0, 0.0)) == "stuck"
    assert io.cmds[-1] == (0.0, 0.0) and io.t < 5.0


def test_reaches_the_goal_at_the_robot_speed(occ):
    io = SimIO(occ, (0.0, 0.0, 0.0))
    r = runner(io, occ, speed=0.12)                     # the speed objmem.sh uses
    assert r.go((6.0, -3.0), goal_yaw=0.0) == "ok"
    assert math.hypot(io.p[0] - 6.0, io.p[1] + 3.0) < 0.2
    assert only_four_commands(io.cmds, r.speed, r.turn_rate)
    assert io.t < 120.0


def test_map_file_gives_the_same_grid_as_the_occupancy_topic(occ, tmp_path):
    from PIL import Image
    # map_server convention: white (254) free, black (0) occupied, image row 0 = top (largest y)
    img = np.where(occ[::-1] == 0, 254, 0).astype(np.uint8)
    Image.fromarray(img).save(str(tmp_path / "aisle_nav.pgm"))
    (tmp_path / "aisle_nav.yaml").write_text(
        "image: aisle_nav.pgm\nmode: trinary\nresolution: 0.05\norigin: [-1.0, -5.0, 0]\n"
        "negate: 0\noccupied_thresh: 0.65\nfree_thresh: 0.196\n")
    from_file = gn.grid_from_map_file(str(tmp_path / "aisle_nav.yaml"), 0.2)
    from_topic = make_grid(occ, 0.2)
    assert from_file.res == from_topic.res and (from_file.ox, from_file.oy) == (from_topic.ox, from_topic.oy)
    assert np.array_equal(from_file.free, from_topic.free)
    segs, _ = gn.plan(from_file, (0.0, 0.0), 0, (6.0, -3.0))
    assert [k for k, _x, _y in segs] == [0, 3, 0]


def test_map_file_grey_unknown_is_blocked(tmp_path):
    from PIL import Image
    img = np.full((40, 40), 205, np.uint8)      # Cartographer grey = unknown
    img[10:30, 10:30] = 254
    Image.fromarray(img).save(str(tmp_path / "m.pgm"))
    (tmp_path / "m.yaml").write_text("image: m.pgm\nresolution: 0.05\norigin: [0, 0, 0]\nnegate: 0\nfree_thresh: 0.196\n")
    g = gn.grid_from_map_file(str(tmp_path / "m.yaml"), 0.0)
    assert g.free.sum() == 400 and not g.free[0, 0]


def test_each_plan_is_reported_for_the_map_view(occ):
    io = SimIO(occ, (0.0, 0.0, 0.0))
    plans = []
    io.on_plan = lambda points, goal: plans.append((list(points), tuple(goal)))
    assert runner(io, occ).go((6.0, -3.0)) == "ok"
    pts, goal = plans[0]
    assert pts[0] == (0.0, 0.0) and len(pts) == 4               # start + three corners/end
    assert goal == pytest.approx((6.0, -3.0), abs=0.06)


def test_a_broken_plan_listener_does_not_stop_the_robot(occ):
    io = SimIO(occ, (0.0, 0.0, 0.0))

    def broken(points, goal):
        raise RuntimeError("viewer gone")
    io.on_plan = broken
    assert runner(io, occ).go((3.0, -2.0)) == "ok"


def test_at_the_goal_it_looks_around_three_times_and_ends_on_the_heading(occ):
    io = SimIO(occ, (0.0, 0.0, 0.0))
    r = runner(io, occ, wiggle_reps=3, wiggle_deg=15.0, wiggle_pause_s=1.0)
    t_heads = []
    real_cmd = io.cmd

    def cmd(v, w):
        real_cmd(v, w)
        t_heads.append(io.p[2])
    io.cmd = cmd
    assert r.go((3.0, -2.0), goal_yaw=-math.pi / 2) == "ok"
    assert abs(wrap(io.p[2] + math.pi / 2)) < math.radians(3)          # back on the goal heading
    tail = t_heads[-400:]                                               # the look-around at the end
    peak = max(wrap(h + math.pi / 2) for h in tail)
    assert math.radians(13) < peak < math.radians(19)                   # turned about 15 degrees
    # three times out and back: the turn direction changes 6 times
    signs = [1 if w > 0 else -1 for _v, w in io.cmds if w != 0.0]
    changes = sum(1 for a, b in zip(signs, signs[1:]) if a != b)
    assert changes >= 5
    assert only_four_commands(io.cmds, r.speed, r.turn_rate)


def test_no_look_around_by_default(occ):
    io = SimIO(occ, (0.0, 0.0, 0.0))
    r = runner(io, occ)
    assert r.wiggle_reps == 0 and r.go((3.0, -2.0), goal_yaw=-math.pi / 2) == "ok"
