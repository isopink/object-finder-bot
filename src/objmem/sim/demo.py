"""The offline demo story (proposal section 8) in the toy world.

patrol -> remember -> "Where is the blue mug?" -> move the mug -> patrol the
other side of the room -> same query: the old place fails, its confidence
drops, the new place succeeds -> a last full patrol forgets the old place.
"""
import math
import os
from typing import Callable, Optional

from objmem.sim.runner import Sim, distance
from objmem.types import Params

QUERY = "Where is the blue mug?"
TARGET = "blue_mug"
NEW_SPOT = (5.0, 0.65)


def _items_table(sim: Sim, say: Callable[[str], None]) -> None:
    truth = sim.world.truth()
    say("  {:>3}  {:<11} {:>6} {:>6} {:>5} {:>5}  {}".format("id", "label", "x", "y", "p", "n_obs", "nearest object"))
    for it in sorted(sim.memory.items, key=lambda i: i.id):
        near = min(truth, key=lambda n: math.hypot(truth[n][0] - it.mu[0], truth[n][1] - it.mu[1]))
        d = math.hypot(truth[near][0] - it.mu[0], truth[near][1] - it.mu[1])
        tag = "{} ({:.2f} m)".format(near, d) if d <= 0.5 else "none within 0.5 m"
        say("  {:>3}  {:<11} {:>6.2f} {:>6.2f} {:>5.2f} {:>5d}  {}".format(
            it.id, str(it.label), float(it.mu[0]), float(it.mu[1]), it.p, it.n_obs, tag))


def _candidates(sim: Sim, say) -> None:
    for rank, c in enumerate(sim.candidates(QUERY)):
        say("  {}. #{} at ({:.2f}, {:.2f})  sim={:.3f}  p={:.2f}  score={:.3f}".format(
            rank + 1, c.item.id, float(c.item.mu[0]), float(c.item.mu[1]), c.sim, c.item.p, c.score))


def run_demo(mode: str = "depth", seed: int = 2, params: Optional[Params] = None,
             say: Callable[[str], None] = print, figure_dir: Optional[str] = None) -> dict:
    """Print the story. Returns a summary dict (used by the tests)."""
    sim = Sim(mode=mode, seed=seed, params=params)
    t0 = sim.world.t

    def clock() -> str:
        return "[t={:6.1f} s]".format(sim.world.t - t0)

    def status(msg: str) -> None:
        say("    finder: " + msg)

    summary = {"mode": mode, "seed": seed}
    mug = sim.world.object(TARGET)
    say("== Offline demo, camera mode '{}' ({}), seed {} ==".format(
        mode, "RealSense color + depth" if mode == "depth" else "C920 color only, bearing-only EKF", seed))
    say("Toy room {:.0f} m x {:.0f} m, {} desks, {} objects. The blue mug is at ({:.2f}, {:.2f}).".format(
        sim.world.width, sim.world.height, len(sim.world.desks), len(sim.world.objects), mug.x, mug.y))

    say("")
    say("Step 1. Patrol the room and remember what the camera sees.")
    st = sim.patrol()
    say("{} {} stops, {} detections, {} observations placed on the map -> {} memories".format(
        clock(), st.frames, st.detections, st.observations, len(sim.memory.items)))
    _items_table(sim, say)
    if figure_dir:
        say("  (map figure: {})".format(_figure(sim, figure_dir, "demo_{}_1_patrol.png".format(mode), "after the first patrol")))

    say("")
    say("Step 2. Query: \"{}\"".format(QUERY))
    _candidates(sim, say)
    r1 = sim.ask(QUERY, on_status=status)
    d1 = distance(r1.item, (mug.x, mug.y))
    say("{} result: {}, tried {}; remembered position is {:.2f} m from the mug".format(clock(), r1.status, r1.tried, d1))
    summary["first"] = (r1.status, r1.tried, d1)
    old_id = r1.item.id if r1.item is not None else None

    say("")
    say("Step 3. Someone moves the blue mug from ({:.2f}, {:.2f}) to ({:.2f}, {:.2f}).".format(
        mug.x, mug.y, NEW_SPOT[0], NEW_SPOT[1]))
    sim.world.move(TARGET, *NEW_SPOT)

    say("")
    say("Step 4. Patrol the south side of the room only (the old place is not seen).")
    st = sim.patrol(part="south")
    say("{} {} stops, {} detections -> {} memories".format(clock(), st.frames, st.detections, len(sim.memory.items)))
    new = sim.item_near(TARGET)
    if old_id is not None:
        old = sim.memory.get(old_id) if hasattr(sim.memory, "get") else None
        if old is not None:
            say("  old memory #{} at ({:.2f}, {:.2f}): p={:.2f} (only time decay so far)".format(
                old.id, float(old.mu[0]), float(old.mu[1]), old.p))
    if new is not None:
        say("  new memory #{} at ({:.2f}, {:.2f}): p={:.2f}, n_obs={}".format(
            new.id, float(new.mu[0]), float(new.mu[1]), new.p, new.n_obs))
    if figure_dir:
        say("  (map figure: {})".format(_figure(sim, figure_dir, "demo_{}_2_moved.png".format(mode), "mug moved, south patrol")))

    say("")
    say("Step 5. Same query again: \"{}\"".format(QUERY))
    _candidates(sim, say)
    p_old_before = sim.memory.get(old_id).p if old_id is not None else None
    r2 = sim.ask(QUERY, on_status=status)
    d2 = distance(r2.item, NEW_SPOT)
    p_old_after = sim.memory.get(old_id).p if old_id is not None else None
    say("{} result: {}, tried {}; found memory is {:.2f} m from the mug's new place".format(
        clock(), r2.status, r2.tried, d2))
    old_failed = old_id is not None and (old_id, "not_found") in r2.tried
    if old_failed:
        say("  old place failed the re-check: p of #{} dropped {:.2f} -> {:.2f}".format(old_id, p_old_before, p_old_after))
    elif old_id is not None:
        say("  the old place #{} was not visited (the new memory already ranked first); p={:.2f}".format(
            old_id, p_old_after))
    if r2.status == "found" and d2 <= 0.5:
        say("  new place succeeded: memory #{} at ({:.2f}, {:.2f}), p={:.2f}".format(
            r2.item.id, float(r2.item.mu[0]), float(r2.item.mu[1]), r2.item.p))
    summary["second"] = (r2.status, r2.tried, d2)
    summary["old_failed"] = old_failed
    summary["p_old"] = (p_old_before, p_old_after)

    say("")
    say("Step 6. A full patrol: the old place is in view and empty, so its confidence keeps falling.")
    sim.patrol()
    if old_id is not None:
        say("{} old memory #{}: p={:.2f}".format(clock(), old_id, sim.memory.get(old_id).p))
        summary["p_old_final"] = sim.memory.get(old_id).p
    say("  candidates now:")
    _candidates(sim, say)
    if figure_dir:
        say("  (map figure: {})".format(_figure(sim, figure_dir, "demo_{}_3_final.png".format(mode), "after the last patrol")))
    say("== end of demo ==")
    return summary


def _figure(sim: Sim, folder: str, name: str, title: str) -> str:
    from objmem.viz import save_map
    path = save_map(os.path.join(folder, name), sim.memory.items, robot_pose=sim.world.robot,
                    occupancy=sim.world.occupancy(), truth=sim.world.truth(), path=sim.world.trail[-40:],
                    title="{} camera: {}".format(sim.mode, title))
    return path
