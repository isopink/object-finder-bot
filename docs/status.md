# Status

What has run on the robot, what is in the code but has not run there yet, and
what is still open.

Last update: 2026-11-28, after the first full run and the changes that followed it.
The version of this file from the integration of 2026-11-16 (before any run on
the robot): `git show 0c4ba57:docs/status.md`.

## Summary

| | State |
|---|---|
| Full loop on the robot | **Ran on 2026-11-28**: remember while patrolling, ask, drive, re-check. 3 of 3 queries found (cup, laptop, cup). Commit `0c4ba57` |
| Changes after that run | In `main`, tests and CI pass, **not yet run on the robot** (list below) |
| Next lab days | Mon 12/1 to Wed 12/3 |
| Presentation | 2026-12-10 (`docs/presentation/`) |

## Ran on the robot (2026-11-18 to 2026-11-28)

Details and logs: `docs/lab/<date>/`, problems and fixes: `docs/lab/트러블슈팅_기록.md` (40 entries).

| Part | What runs | Notes |
|---|---|---|
| Install | ROS 2 Foxy native on the Jetson (JetPack 5) | Humble in Docker was never needed |
| Bringup | OpenCR, LDS-02 | LiDAR mounted backwards: scan turned 180° (`OFB_SCAN_ROTATE_DEG`); 240 beams per scan fixed for SLAM (troubleshooting 15, 27) |
| Odometry | Own wheel odometry (`robot/lib/wheel_odom.py`, `OFB_WHEEL_ODOM=1`) | The driver's `/odom` heading froze twice (18, 28, 36) |
| Middleware | Fast DDS with discovery over 40 ports (`OFB_DDS_WIDE=1`) | Late nodes found nobody (23) |
| Mapping | Cartographer, driven with the four-key teleop (`teleop4.sh`) | slam_toolbox exits at start (24); free turns bent the map (29). Map `room_l4` |
| Navigation map | Aisles only (`robot/lib/make_nav_map.py`) | The 2D LiDAR sees desk legs, not desk tops (26) |
| Localization | AMCL on the full map; `./robot/relocalize.sh` matches the scan when the robot starts elsewhere | AMCL on the aisle map was 1.8 m off (34) |
| Driving | `gridnav`: straight lines and exact 90° turns, look-around at the goal | Nav2 failed in the narrow aisles (25, 30). Nav2 alone reached a 1 m goal within 0.09 m |
| Camera | RealSense D455f, measured intrinsics (fx 386.98) and mount | The worker reopens a stalled stream (32, 33) |
| Detection | NanoOWL (prompts "a cup, a laptop"), about 0.08 s per frame with depth | detectNet missed a clear bottle |
| Vision worker | CLIP on the GPU, 4.2 GB; page cache dropped while the models load | Restart failed out of GPU memory before that (11, 31) |
| Memory | Observing while driving straight and when stopped, not while turning | 2 looks per second asked, 1.76 measured |
| Questions | Typed in the `ask` pane, or spoken on the laptop (faster-whisper) | Whisper on the Jetson did not fit next to the worker |
| Viewing | Map view on 8555, live camera on 8601 (about 10 frames per second) | Live view was 2 to 4 frames per second before (35) |

The full loop has run with the D455f (`depth`) only. `nodepth` (C920) is
tested on the PC and was used for the camera before 2026-11-27.

## In main, not yet run on the robot

All on by default in `robot/config/depth.yaml` and the robot scripts. If the
robot misbehaves, check them in this order and turn off one at a time:

| # | Change | Commit | Check on the robot | Turn off |
|---|---|---|---|---|
| 1 | 5 looks per second (was 2) | `5eb14d4` | Time between `observe:` lines; live view still smooth | `export OFB_OBSERVE_RATE=2.0` |
| 2 | NanoOWL also asks for "a computer monitor" and drops those boxes | `cda07ca` | Monitors gray in the live view, a real laptop still green | `export OFB_OWL_DISTRACTORS=none` |
| 3 | One object, one memory: same-label gate 0.5, merge within 0.2 m, position std at least 3 cm | `ef12fab`, `b1d216b` | One memory per object on the map; two objects side by side not merged | `cos_thresh_same_label`, `merge_dist`, `pos_std_min`: `0` |
| 4 | p updated at most once per 0.2 m of robot travel | `0e14f58` | p of a far object does not fall while driving towards it | `p_update_dist: 0` |
| 5 | Evidence log per run, `d_by_range` table, `robot/fit_detection.sh` | `0faf3ec`, `22ed4a8` | `robot/logs/<run>/evidence.jsonl` grows; the script prints a table | `d_by_range: []` (empty until measured) |
| 6 | Blue line of the path driven on the map view | `8ebdee1` | Line follows the robot, breaks after `./reloc` | |

If nothing helps: `git checkout 0c4ba57`, the setup of 2026-11-28.

Behavior to know about these changes:

- With rule 4 the robot must move to change p: standing in front of an object
  that is taken away does not lower its p until the robot drives on or re-checks.
- Rule 2 fails if NanoOWL calls a real laptop "computer monitor": then the
  laptop is dropped too. Check this first with a laptop on a desk.
- Memories of monitors already saved as laptops stay until they decay or are
  seen empty; start with a new memory file to be rid of them.
- Rule 3 can merge two objects of the same kind placed closer than 0.2 m.

## Open

| Problem | State |
|---|---|
| Robot evidence that probabilistic memory finds a moved object | Only in the toy world (below); to film on the robot |
| P(detect \| present) by distance | Tools ready; measure with the cup kept in place, then `./robot/fit_detection.sh --apply cup` |
| A question about an object never seen | The robot drives to the closest memory and re-checks up to 3 candidates (no "I don't know") |
| Battery | Down to 11.5 V on 11/28 (about 3 h from 12.5 V); charge before filming |
| `/odom` NaN once (11/27 23:10) | Not seen again since the wheel odometry; cause unknown |
| Jetson reboots | Cause unknown, power cable contact suspected (13) |
| Start tape 0.49 m behind the map origin | Start the next map on the tape |
| Jetson memory | About 200 MB really free while everything runs; restart only the ROS side (`stop_all.sh --keep-worker`) |

## Verified on a PC

`pip install -e ".[dev]"`, then from the repository root:

| Command | Result |
|---|---|
| `pytest` | 482 passed (Python 3.13; includes `ros/objmem_ros/test`, the Python 3.8 syntax check of every `.py`, `bash -n` on every `.sh`) |
| `python scripts/demo_offline.py --camera depth` / `nodepth` | Mug found; after the move the old place fails and the new place is found |
| `python scripts/evaluate.py` | Tables below |
| `python scripts/merge_memory.py docs/lab/20261128/memory_room_l4_nav_depth.npz --config robot/config/depth.yaml` | Merges the two laptop memories 9 cm apart, nothing else |

CI on GitHub Actions, green for every commit in `main` up to `e5303e3`:

| Workflow | Jobs |
|---|---|
| `tests.yml` | `pytest` on Python 3.8 and 3.10 |
| `ros.yml` | `ros:foxy` and `ros:humble`: `colcon build`, unit tests, finder end to end with a fake worker and fake navigator, launch smoke test |

### Evaluation in the toy world (`python scripts/evaluate.py`)

5 seeds x 20 queries per row; success = re-check passed and position within 0.5 m.
The changes listed above leave these numbers unchanged (the toy world has no
duplicates, no look-alikes, and perfect localization).

| camera | search | top-1 | top-3 | pos. error mean (m) | median (m) |
|---|---|---|---|---|---|
| depth | CLIP | 95.0% | 95.0% | 0.238 | 0.024 |
| depth | label match | 43.0% | 45.0% | 1.743 | 0.047 |
| nodepth | CLIP | 95.0% | 95.0% | 0.244 | 0.012 |
| nodepth | label match | 44.0% | 44.0% | 1.691 | 0.024 |

After moving 4 objects and patrolling again:

| camera | memory | moved: top-1 | moved: top-3 | moved: visits / query |
|---|---|---|---|---|
| depth | probabilistic | 100.0% | 100.0% | 1.00 |
| depth | baseline (append, similarity only) | 50.0% | 92.5% | 1.80 |
| nodepth | probabilistic | 100.0% | 100.0% | 1.00 |
| nodepth | baseline | 45.0% | 95.0% | 1.75 |

The comparisons matter, not the absolute numbers. The 5 % CLIP failures are
"Where is my phone charger?", which ranks the phone first.

## Evaluation on the robot (to do)

Measure object positions into `data/ground_truth.yaml`, run the queries, then

```bash
python scripts/evaluate.py --memory robot/memory/<map>_<mode>.npz \
    --log robot/memory/search_<map>_<mode>.jsonl \
    --ground-truth data/ground_truth.yaml --map robot/maps/<map>.yaml \
    --config robot/config/<mode>.yaml
```
