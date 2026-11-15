"""Search loop: query text -> ranked memories -> drive there -> re-check the live view.

    result = find("where is the blue mug", memory, embedder, navigator, verifier, params)

For each candidate from ``memory.query`` (best score first):

1. ``navigator.go_to(goal_for(item, params))``.
2. If that fails, retry once with ``item.view_pose`` (the pose the object was
   last seen from, so it is known to be reachable and to see the object).
3. If that fails too, record ``nav_failed`` and go on to the next candidate.
4. On arrival ``verifier.check(text)``: found -> ``memory.mark_found`` and
   return; not found -> ``memory.mark_not_found`` and go on.

Search log
----------
When ``log_path`` is given (or ``params`` has a non-empty ``search_log``
attribute), one JSON object per query is appended to that file, one per line:

    {
      "query": "where is the blue mug",
      "t_start": 1700000000.0, "t_end": 1700000042.0,
      "status": "found",              # found | not_found | nav_failed | empty
      "found_id": 3,                  # null unless status == "found"
      "candidates": [                 # as returned by memory.query, in order
        {"id": 3, "label": "cup", "sim": 0.31, "p": 0.82, "score": 0.55,
         "mu": [1.2, 0.4]}
      ],
      "visits": [                     # in visit order
        {"id": 3, "outcome": "found", # found | not_found | nav_failed
         "goal": [0.7, 0.4, 0.0],     # first goal sent (x, y, yaw)
         "retried_view_pose": false,  # true when the view_pose retry was used
         "prob": 0.91,                # re-check probability, null if not checked
         "error": null,               # text of an exception, if one was caught
         "t_start": 1700000001.0, "t_end": 1700000040.0}
      ]
    }

``read_log(path)`` returns these objects as a list of dicts.
"""
import json
import math
import os
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np

from objmem.types import (
    Candidate,
    Embedder,
    MemoryAPI,
    MemoryItem,
    Navigator,
    Params,
    Pose2D,
    SearchResult,
    Verifier,
)

FOUND = "found"
NOT_FOUND = "not_found"
NAV_FAILED = "nav_failed"
EMPTY = "empty"

# Below this distance (m) the direction view_pose -> object is not meaningful.
_MIN_DIST = 1e-6

StatusCallback = Callable[[str], None]


def goal_for(item: MemoryItem, params: Params) -> Pose2D:
    """Where to stand to look at a remembered object.

    Certain position: the point ``params.standoff`` meters from the object on
    the line toward ``item.view_pose``, facing the object. When the view pose
    is already closer than the standoff, stay at the view position and only
    turn toward the object.

    Uncertain position (largest eigenvalue of ``item.cov`` above
    ``params.pos_cov_max``, or a covariance that is not finite): return
    ``item.view_pose`` unchanged, the pose the object was actually seen from.
    """
    view = item.view_pose
    cov = np.asarray(item.cov, dtype=float).reshape(2, 2)
    mu = np.asarray(item.mu, dtype=float).reshape(2)
    if not (np.all(np.isfinite(cov)) and np.all(np.isfinite(mu))):
        return Pose2D(view.x, view.y, view.yaw)
    largest = float(np.max(np.linalg.eigvalsh(0.5 * (cov + cov.T))))
    if largest > params.pos_cov_max:
        return Pose2D(view.x, view.y, view.yaw)

    dx = float(mu[0]) - view.x
    dy = float(mu[1]) - view.y
    dist = math.hypot(dx, dy)
    if dist < _MIN_DIST:
        # The robot stood on top of the estimate; no direction to face.
        return Pose2D(view.x, view.y, view.yaw)
    yaw = math.atan2(dy, dx)
    if dist <= params.standoff:
        return Pose2D(view.x, view.y, yaw)
    ux, uy = dx / dist, dy / dist
    return Pose2D(float(mu[0]) - params.standoff * ux, float(mu[1]) - params.standoff * uy, yaw)


def _pose_list(pose: Pose2D) -> List[float]:
    return [float(pose.x), float(pose.y), float(pose.yaw)]


def _candidate_record(cand: Candidate) -> Dict[str, Any]:
    item = cand.item
    return {
        "id": int(item.id),
        "label": item.label,
        "sim": float(cand.sim),
        "p": float(item.p),
        "score": float(cand.score),
        "mu": [float(v) for v in np.asarray(item.mu, dtype=float).reshape(-1)[:2]],
    }


def _append_log(path: str, record: Dict[str, Any]) -> None:
    folder = os.path.dirname(os.path.abspath(path))
    if folder and not os.path.isdir(folder):
        os.makedirs(folder)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(record) + "\n")


def read_log(path: str) -> List[Dict[str, Any]]:
    """Read a search log written by ``find``: one dict per query, in order."""
    records = []  # type: List[Dict[str, Any]]
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def _go(navigator: Navigator, pose: Pose2D) -> Tuple[bool, Optional[str]]:
    """navigator.go_to that never raises: an exception counts as a failed goal."""
    try:
        return bool(navigator.go_to(pose)), None
    except Exception as exc:  # noqa: BLE001 - a navigation error must not kill the search
        return False, "navigator: {}: {}".format(type(exc).__name__, exc)


def find(
    text: str,
    memory: MemoryAPI,
    embedder: Embedder,
    navigator: Navigator,
    verifier: Verifier,
    params: Params,
    clock: Callable[[], float] = time.time,
    log_path: Optional[str] = None,
    on_status: Optional[StatusCallback] = None,
) -> SearchResult:
    """Find the object described by ``text``. Blocks until done.

    ``log_path``: append one JSON line for this query (see the module
    docstring). Defaults to ``params.search_log`` when that attribute exists.
    ``on_status``: called with a short English progress line at each step
    (the ROS finder publishes these on /objmem/status).

    Result status: ``found``; ``empty`` when the memory returns no candidate;
    ``not_found`` when at least one candidate was reached and re-checked but
    none passed; ``nav_failed`` when no candidate could be reached at all.
    """
    if log_path is None:
        log_path = params.search_log or None

    def say(message: str) -> None:
        if on_status is not None:
            try:
                on_status(message)
            except Exception:  # noqa: BLE001 - a status listener must not break the search
                pass

    t_start = float(clock())
    say("query: {}".format(text))
    text_embedding = embedder.embed_text(text)
    candidates = list(memory.query(text_embedding, t_start))
    # Snapshot now: mark_found / mark_not_found change item.p later.
    cand_records = [_candidate_record(c) for c in candidates]

    tried = []  # type: List[Tuple[int, str]]
    visits = []  # type: List[Dict[str, Any]]
    found_item = None  # type: Optional[MemoryItem]

    if not candidates:
        say("memory is empty: nothing to search")

    for rank, cand in enumerate(candidates):
        item = cand.item
        name = "#{}{}".format(item.id, " ({})".format(item.label) if item.label else "")
        goal = goal_for(item, params)
        visit = {
            "id": int(item.id),
            "outcome": NAV_FAILED,
            "goal": _pose_list(goal),
            "retried_view_pose": False,
            "prob": None,
            "error": None,
            "t_start": float(clock()),
            "t_end": None,
        }  # type: Dict[str, Any]
        say("candidate {}/{}: {} sim={:.2f} p={:.2f} score={:.2f}; driving to ({:.2f}, {:.2f})".format(
            rank + 1, len(candidates), name, cand.sim, item.p, cand.score, goal.x, goal.y))

        ok, error = _go(navigator, goal)
        if not ok:
            view = item.view_pose
            visit["retried_view_pose"] = True
            say("navigation failed; retrying with the view pose ({:.2f}, {:.2f})".format(view.x, view.y))
            ok, error2 = _go(navigator, Pose2D(view.x, view.y, view.yaw))
            error = error2 or error
        if not ok:
            visit["error"] = error
            visit["t_end"] = float(clock())
            visits.append(visit)
            tried.append((item.id, NAV_FAILED))
            say("navigation failed twice for {}; skipping".format(name))
            continue

        say("arrived; re-checking the live view for '{}'".format(text))
        try:
            found, prob = verifier.check(text)
        except Exception as exc:  # noqa: BLE001
            # No evidence either way (e.g. the vision worker is down): count the
            # visit as not found for the caller, but leave the memory untouched.
            visit["outcome"] = NOT_FOUND
            visit["error"] = "verifier: {}: {}".format(type(exc).__name__, exc)
            visit["t_end"] = float(clock())
            visits.append(visit)
            tried.append((item.id, NOT_FOUND))
            say("re-check error at {}: {}".format(name, exc))
            continue

        now = float(clock())
        visit["prob"] = float(prob)
        visit["t_end"] = now
        if found:
            memory.mark_found(item.id, now)
            visit["outcome"] = FOUND
            visits.append(visit)
            tried.append((item.id, FOUND))
            found_item = item
            say("found {} (prob {:.2f})".format(name, prob))
            break
        memory.mark_not_found(item.id, now)
        visit["outcome"] = NOT_FOUND
        visits.append(visit)
        tried.append((item.id, NOT_FOUND))
        say("not found at {} (prob {:.2f})".format(name, prob))

    if found_item is not None:
        status = FOUND
    elif not candidates:
        status = EMPTY
    elif any(outcome == NOT_FOUND for _, outcome in tried):
        status = NOT_FOUND
    else:
        status = NAV_FAILED
    say("done: {}".format(status))

    if log_path:
        record = {
            "query": text,
            "t_start": t_start,
            "t_end": float(clock()),
            "status": status,
            "found_id": int(found_item.id) if found_item is not None else None,
            "candidates": cand_records,
            "visits": visits,
        }
        try:
            _append_log(log_path, record)
        except OSError as exc:
            say("could not write the search log {}: {}".format(log_path, exc))

    return SearchResult(status=status, item=found_item, tried=tried)
