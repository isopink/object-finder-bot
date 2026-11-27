"""Go to a goal with four commands only: straight, turn right 90, turn left 90, stop.

Nav2 drives curves and turns in place to fit the goal heading. In the narrow aisles of the
classroom that failed (the robot on the edge of the aisle, recoveries spinning). This
navigator plans on the map grid with 4-connected moves (the map axes are the room axes,
because mapping started facing along a wall) and runs the plan as

    turn so that the heading is one of the four axis headings (0, 90, 180, -90 degrees),
    drive straight until the position along that axis reaches the corner, repeat,
    stop.

Position and heading come from the map -> base_link transform (AMCL), so the drift of
the wheels does not add up. The module has no ROS import: `plan()` and `Runner` are tested
on a PC with a simulated robot (test_gridnav.py). `gridnav_node.py` wires it to ROS 2.

Commands the runner sends (checked by the tests): (0, 0), (v, 0) and (0, +-w) only,
never a curve.
"""
import heapq
import math

import numpy as np

HALF_PI = math.pi / 2.0
# heading index k (0..3) -> unit step in the map grid and yaw = k * 90 degrees
STEPS = [(1, 0), (0, 1), (-1, 0), (0, -1)]


def wrap(a):
    return (a + math.pi) % (2.0 * math.pi) - math.pi


def snap_heading(yaw):
    """Nearest axis heading index (0: +x, 1: +y, 2: -x, 3: -y) for a yaw in radians."""
    return int(round(wrap(yaw) / HALF_PI)) % 4


# ---------------------------------------------------------------- grid
class Grid(object):
    """Free-space grid. free[iy, ix] is True where the robot centre may be (obstacles already
    grown by the robot radius). World point (x, y) is in cell ((x - ox) / res, (y - oy) / res)."""

    def __init__(self, free, res, origin, keep_off_m=0.5, keep_off_cost=1.5):
        self.free = np.asarray(free, dtype=bool)
        self.res = float(res)
        self.ox, self.oy = float(origin[0]), float(origin[1])
        # Extra cost per step near walls, so corners are planned in the middle of the aisle and
        # not 20 cm from a wall (where the front LiDAR stop would trigger).
        levels = max(1, int(round(keep_off_m / self.res)))
        dist = np.zeros(self.free.shape, dtype=np.float32)
        cur = self.free.copy()
        for _ in range(levels):
            dist += cur
            nxt = cur.copy()
            nxt[1:, :] &= cur[:-1, :]
            nxt[:-1, :] &= cur[1:, :]
            nxt[:, 1:] &= cur[:, :-1]
            nxt[:, :-1] &= cur[:, 1:]
            nxt[0, :] = nxt[-1, :] = False
            nxt[:, 0] = nxt[:, -1] = False
            cur = nxt
        self.pen = keep_off_cost * (1.0 - np.minimum(dist, levels) / levels)

    def cell(self, x, y):
        return int(math.floor((x - self.ox) / self.res)), int(math.floor((y - self.oy) / self.res))

    def centre(self, ix, iy):
        return self.ox + (ix + 0.5) * self.res, self.oy + (iy + 0.5) * self.res

    def inside(self, ix, iy):
        return 0 <= iy < self.free.shape[0] and 0 <= ix < self.free.shape[1]

    def is_free(self, ix, iy):
        return self.inside(ix, iy) and bool(self.free[iy, ix])

    def nearest_free(self, ix, iy, max_m):
        """The free cell closest to (ix, iy) within max_m metres, or None."""
        if self.is_free(ix, iy):
            return ix, iy
        r_max = int(math.ceil(max_m / self.res))
        best, best_d = None, None
        for dy in range(-r_max, r_max + 1):
            for dx in range(-r_max, r_max + 1):
                d = math.hypot(dx, dy)
                if d <= r_max and self.is_free(ix + dx, iy + dy) and (best_d is None or d < best_d):
                    best, best_d = (ix + dx, iy + dy), d
        return best


def grid_from_occupancy(data, width, height, res, origin, radius_m, free_max=0):
    """Grid from a nav_msgs/OccupancyGrid body: free = value in [0, free_max]; unknown (-1)
    and occupied are blocked. Free space shrinks by the robot radius (the border of the map
    counts as blocked)."""
    a = np.asarray(data, dtype=np.int16).reshape(int(height), int(width))
    free = (a >= 0) & (a <= free_max)
    return Grid(erode(free, int(math.ceil(radius_m / res))), res, origin)


def erode(free, r):
    """Cells whose whole disc of radius r (cells) is free; outside the array counts as blocked."""
    if r <= 0:
        return free.copy()
    h, w = free.shape
    blocked = np.pad(~free, r, mode="constant", constant_values=True)
    grown = np.zeros_like(free)
    for dy in range(-r, r + 1):
        for dx in range(-r, r + 1):
            if dx * dx + dy * dy <= r * r:
                grown |= blocked[r + dy:r + dy + h, r + dx:r + dx + w]
    return free & ~grown


# ---------------------------------------------------------------- planner
def plan(grid, start_xy, start_k, goal_xy, turn_cost_m=0.6, max_snap_m=0.7):
    """Axis-aligned path from start to goal.

    Returns (segments, goal_xy_used) or (None, None). segments = [(k, ex, ey), ...]: heading
    index k and the world end point of each straight run. The start and the goal move to the
    nearest free cell within max_snap_m (the robot may stand inside the grown obstacles).
    The cost is path length plus turn_cost_m per 90 degree turn, so the path has few turns.
    """
    s = grid.nearest_free(*grid.cell(*start_xy), max_m=max_snap_m)
    g = grid.nearest_free(*grid.cell(*goal_xy), max_m=max_snap_m)
    if s is None or g is None:
        return None, None
    res = grid.res
    tc = turn_cost_m / res                     # in cells
    start = (s[0], s[1], start_k % 4)
    best = {start: 0.0}
    prev = {}
    heap = [(abs(g[0] - s[0]) + abs(g[1] - s[1]), 0.0, start)]
    goal_state = None
    while heap:
        _f, cost, st = heapq.heappop(heap)
        if cost > best.get(st, 1e18):
            continue
        ix, iy, k = st
        if (ix, iy) == g:
            goal_state = st
            break
        for k2 in range(4):
            if (k2 - k) % 4 == 2:
                continue                       # no U-turns: they are two 90 degree turns, planned as a detour
            dx, dy = STEPS[k2]
            nx, ny = ix + dx, iy + dy
            if not grid.is_free(nx, ny):
                continue
            c = cost + 1.0 + float(grid.pen[ny, nx]) + (tc if k2 != k else 0.0)
            st2 = (nx, ny, k2)
            if c < best.get(st2, 1e18):
                best[st2] = c
                prev[st2] = st
                heapq.heappush(heap, (c + abs(g[0] - nx) + abs(g[1] - ny), c, st2))
    if goal_state is None:
        return None, None
    cells = [goal_state]
    while cells[-1] in prev:
        cells.append(prev[cells[-1]])
    cells.reverse()                            # start .. goal, each (ix, iy, k) with k = heading used to enter
    segs = []                                  # merge runs with the same heading
    for ix, iy, k in cells[1:]:
        if segs and segs[-1][0] == k:
            segs[-1] = (k, ix, iy)
        else:
            segs.append((k, ix, iy))
    out = [(k, grid.centre(ix, iy)[0], grid.centre(ix, iy)[1]) for k, ix, iy in segs]
    return out, grid.centre(*g)


# ---------------------------------------------------------------- runner
class Runner(object):
    """Executes plans with the four commands. `io` provides:

        pose() -> (x, y, yaw) in the map frame, or None when unknown
        cmd(v, w)           publish a velocity (only (0,0), (v,0), (0,+-w) are used)
        front() -> metres to the nearest thing straight ahead
        now() -> seconds, sleep(s), cancelled() -> bool, log(text)
    """

    def __init__(self, io, grid_fn, speed=0.08, turn_rate=0.25, front_stop=0.30, goal_tol=0.15,
                 lateral_tol=0.30, lead_deg=0.5, blocked_wait_s=6.0, max_replans=8, dt=0.05):
        self.io, self.grid_fn = io, grid_fn
        self.speed, self.turn_rate, self.front_stop = speed, turn_rate, front_stop
        self.goal_tol, self.lateral_tol = goal_tol, lateral_tol
        self.lead, self.blocked_wait_s = math.radians(lead_deg), blocked_wait_s
        self.max_replans, self.dt = max_replans, dt

    # -- the four commands
    def stop(self):
        for _ in range(5):
            self.io.cmd(0.0, 0.0)
            self.io.sleep(0.02)

    def _pose_or_wait(self, timeout=1.0):
        t0 = self.io.now()
        while True:
            p = self.io.pose()
            if p is not None:
                return p
            if self.io.now() - t0 > timeout:
                return None
            self.io.sleep(self.dt)

    def turn_to(self, k, timeout_s=25.0):
        """Turn in place (right or left, 90 degrees at a time) until the heading is axis k.
        Returns "ok", "lost" (no pose) or "cancel"/"timeout"."""
        target = k * HALF_PI
        t0 = self.io.now()
        while True:
            if self.io.cancelled():
                self.stop(); return "cancel"
            if self.io.now() - t0 > timeout_s:
                self.stop(); return "timeout"
            p = self._pose_or_wait()
            if p is None:
                self.stop(); return "lost"
            d = wrap(target - p[2])
            if abs(d) <= max(self.lead, math.radians(1.0)):
                self.stop(); return "ok"
            w = self.turn_rate if d > 0 else -self.turn_rate
            # near the target the last 0.5 degrees are covered by the stopping delay
            self.io.cmd(0.0, w)
            self.io.sleep(self.dt)

    def drive_to(self, k, ex, ey):
        """Straight along axis k until the position along that axis reaches the end point.
        Returns "ok", "blocked", "drift" (left the line, replan), "lost", "cancel"."""
        ax = 0 if k in (0, 2) else 1
        sign = 1.0 if k in (0, 1) else -1.0
        end = (ex, ey)
        blocked_since = None
        while True:
            if self.io.cancelled():
                self.stop(); return "cancel"
            p = self._pose_or_wait()
            if p is None:
                self.stop(); return "lost"
            remaining = sign * (end[ax] - p[ax])
            if remaining <= 0.02:
                self.stop(); return "ok"
            if abs(p[1 - ax] - end[1 - ax]) > self.lateral_tol or abs(wrap(k * HALF_PI - p[2])) > math.radians(12):
                self.stop(); return "drift"
            if self.io.front() < self.front_stop:
                self.io.cmd(0.0, 0.0)
                now = self.io.now()
                blocked_since = now if blocked_since is None else blocked_since
                if now - blocked_since > self.blocked_wait_s:
                    self.stop(); return "blocked"
                self.io.sleep(self.dt)
                continue
            blocked_since = None
            v = min(self.speed, 0.4 * remaining + 0.02)     # slow down on the last 10 cm
            self.io.cmd(v, 0.0)
            self.io.sleep(self.dt)

    def go(self, goal_xy, goal_yaw=None, max_time_s=180.0):
        """Drive to goal_xy (map metres), then turn to the axis heading nearest goal_yaw.
        Returns "ok" or a failure word: "no_path", "lost", "blocked", "timeout", "cancel"."""
        t0 = self.io.now()
        last = "no_path"
        for attempt in range(self.max_replans + 1):
            p = self._pose_or_wait()
            if p is None:
                return "lost"
            grid = self.grid_fn()
            segs, used = plan(grid, (p[0], p[1]), snap_heading(p[2]), goal_xy)
            if segs is None:
                self.io.log("no axis-aligned path from (%.2f, %.2f) to (%.2f, %.2f)" % (p[0], p[1], goal_xy[0], goal_xy[1]))
                return "no_path"
            self.io.log("plan #%d: %s" % (attempt + 1, " ".join("%s%.2f" % ("+x +y -x -y".split()[k], math.hypot(ex - p[0], ey - p[1])) for k, ex, ey in segs)))
            status = "ok"
            for k, ex, ey in segs:
                if self.io.now() - t0 > max_time_s:
                    self.stop(); return "timeout"
                status = self.turn_to(k)
                if status == "ok":
                    status = self.drive_to(k, ex, ey)
                if status != "ok":
                    break
            if status in ("cancel", "lost", "timeout"):
                return status
            last = status
            p = self._pose_or_wait()
            if p is None:
                return "lost"
            if status == "ok" and math.hypot(p[0] - used[0], p[1] - used[1]) <= self.goal_tol + 0.03:
                break
            # drift, blocked or stopped short of the goal: plan again from where the robot is
        else:
            return last if last != "ok" else "blocked"
        if goal_yaw is not None:
            st = self.turn_to(snap_heading(goal_yaw))
            if st != "ok":
                return st
        self.stop()
        return "ok"
