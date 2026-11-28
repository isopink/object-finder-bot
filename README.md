# Object-Finding Robot with Natural-Language Queries

> "Where is the cup?" The robot searches its memory and drives to where it last saw the cup.

A TurtleBot3 Waffle Pi patrols a room and remembers the objects it sees on desks
as a **CLIP embedding, a map position, a timestamp, and an existence
confidence**. Given an English description, it picks the best memory, drives
there, and re-checks the live camera view. If the object is gone, the
confidence drops and the robot tries the next candidate.

Course project for Intelligent Robotics at the University of Seoul (Fall 2026).
Design and equations: [docs/proposal.md](docs/proposal.md). What has run on the
robot and what is still to check there: [docs/status.md](docs/status.md).
The first full run (2026-11-28, 3 of 3 queries found) and how to start that
setup: [docs/lab/20261128/README.md](docs/lab/20261128/README.md). Every problem
met on the way: [docs/lab/트러블슈팅_기록.md](docs/lab/트러블슈팅_기록.md).

## How it works

Everything that drives the robot runs on the Jetson Xavier NX mounted on it.
The team works over SSH from a Windows laptop: questions are spoken or typed,
the live camera and the map are viewed in a browser.

```
Jetson Xavier NX (on the robot; JetPack 5.1.5, ROS 2 Foxy native)
 ├─ robot bringup      OpenCR, LDS-02 LiDAR (scan turned 180 deg), own wheel odometry
 ├─ ROS 2 side         Cartographer for mapping; AMCL on the full map;
 │                     gridnav (straight lines, exact 90 deg turns) on the aisle map;
 │                     objmem_ros nodes: observer, finder, mapview
 └─ vision worker      conda Python 3.8, no ROS: RealSense D455f + NanoOWL + CLIP,
                       HTTP JSON server on port 8600
Laptop (Windows)       SSH windows, browser, spoken questions (faster-whisper)
```

| Port | What |
|------|------|
| 8555 | Map view: map, robot, remembered objects, planned route (orange), path driven (blue), start mark (X) |
| 8600 | Vision worker (`scripts/vision_worker.py`) |
| 8601 | Live camera: detections (green), dropped look-alikes (gray), re-check (yellow) |
| 8554 | WebRTC video of the camera-only demo (`vision/find_object.py`) |

Each memory holds a position mean and covariance, a CLIP image embedding, the
last-seen time, and an existence confidence `p`:

| Field | Update |
|-------|--------|
| Position `μ`, `Σ` | Kalman update with depth (RealSense); EKF bearing update without depth (C920); std kept at `pos_std_min` or more |
| Embedding `e` | Running mean of the CLIP crop embeddings |
| Confidence `p` | Bayes update on seen / not seen while in view, at most once per `p_update_dist` of robot travel; time decay toward 0.5 |

Search score = `softmax(cos(text, e) / T) × p`. The robot visits the top 3 in
order and re-checks the live view with CLIP against background prompts.

Two camera versions are supported end to end, selected by `camera_mode`:
`depth` (Intel RealSense D455f, color + aligned depth; used on the robot since
2026-11-27) and `nodepth` (Logitech C920, color only). `config/default.yaml`
holds the code defaults; the robot reads `robot/config/depth.yaml` or
`robot/config/nodepth.yaml`.

### Changed after the first full run (not yet run on the robot)

All of this is on in `robot/config/depth.yaml` and the robot scripts. The last
setup that ran on the robot is commit `0c4ba57` (`git checkout 0c4ba57`).

| Change | Why | Turn off |
|---|---|---|
| 5 looks per second (was 2) | Remember objects while driving past them | `OFB_OBSERVE_RATE=2.0` |
| `p_update_dist: 0.2` | Frames a few cm apart are one piece of evidence; counted one by one, the cup reached p = 0.9999 | `0` |
| `cos_thresh_same_label: 0.5`, `merge_dist: 0.2`, `pos_std_min: 0.03` | One object had become two or three memories | `0` each |
| NanoOWL also asks for "a computer monitor" and drops those boxes | Monitors were remembered as laptops | `OFB_OWL_DISTRACTORS=none` |
| Evidence log per run, `d_by_range` (empty until measured) | P(detect \| present) by distance, measured with `robot/fit_detection.sh` | `d_by_range: []` |
| Blue line on the map view | Where the robot has been since the view started | |

## Repository

| Path | Contents |
|------|----------|
| `src/objmem/` | The Python package (no ROS): memory, geometry, search, vision, toy world |
| `config/default.yaml` | Every tunable value with its code default |
| `robot/config/` | The values the robot uses (`depth.yaml`, `nodepth.yaml`). In the classroom edit these, not the code |
| `scripts/` | `vision_worker.py`, `demo_offline.py`, `evaluate.py`, `tune_verify.py`, `merge_memory.py`, `fit_detection_range.py`; laptop tools in `laptop_tools/` and `laptop_voice/` |
| `ros/objmem_ros/` | ROS 2 package: `observer`, `finder`, `mapview`, `ask`, `gridnav`, launch file ([ros/README.md](ros/README.md)) |
| `robot/` | Bash scripts for the Jetson on the robot, one per step ([robot/README.md](robot/README.md)); maps in `robot/maps/` |
| `vision/` | Camera-only demo and benchmarks for the Jetson ([vision/README.md](vision/README.md)) |
| `data/` | Query set and ground-truth template for the evaluation |
| `tests/` | `pytest` suite, runs on a PC with fakes |
| `docs/` | Design, status, lab records and troubleshooting log (`lab/`), presentation (`presentation/`) |

Package modules:

| Module | Role |
|--------|------|
| `objmem.types` | Shared data types, `Params`, interfaces |
| `objmem.memory` | `ObjectMemory`: association, Kalman / EKF fusion, Bayes update, decay, merging, evidence log, save/load |
| `objmem.geometry`, `objmem.bearing` | Detection + robot pose -> map position and covariance |
| `objmem.search` | Query -> candidates -> drive -> re-check loop |
| `objmem.embed`, `crops`, `verify` | CLIP embedder, crop generators, live re-check |
| `objmem.worker` | Vision worker HTTP server and client, live camera view |
| `objmem.detectors`, `objmem.camera` | NanoOWL / detectNet / YOLO and RealSense / C920 adapters |
| `objmem.speech` | Whisper speech queries on the Jetson (replaced by the laptop: `scripts/laptop_voice/`) |
| `objmem.sim`, `objmem.viz` | Toy world for offline runs, map drawing |

## On a PC: tests and the offline demo

Python 3.8 or newer. No GPU, ROS, or camera needed.

```bash
git clone https://github.com/isopink/object-finder-bot.git
cd object-finder-bot
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e ".[dev]"

pytest                                         # whole test suite
python scripts/demo_offline.py --camera depth  # patrol, query, move the mug, query again
python scripts/demo_offline.py --camera nodepth
python scripts/evaluate.py                     # report tables (proposal section 7)
python scripts/vision_worker.py --fake         # vision worker with fakes on port 8600
```

With the fake worker running, from another terminal:

```bash
curl http://127.0.0.1:8600/health
curl -X POST -d '{"text": "a blue mug"}' http://127.0.0.1:8600/verify
```

## In the classroom

[robot/README.md](robot/README.md) goes through installation and the first
checks stage by stage. Once the robot is set up, the run of 2026-11-28 started
like this on the Jetson (D455f, NanoOWL, map `room_l4`):

```bash
cd ~/object-finder-bot && git pull
export OFB_DDS_WIDE=1 OFB_ODOM_IMU=0 OFB_DETECTOR=owl OFB_OWL_PROMPTS="a cup,a laptop" OFB_TILES=0
./robot/start_all.sh room_l4_nav depth
```

- Put the robot on the start tape (the X on the map view) before starting;
  elsewhere, run `./robot/relocalize.sh` afterwards.
- Ask in the `ask` pane (`q where is the cup`) or by voice from the laptop
  (`scripts/laptop_voice/음성질문.cmd`).
- Watch the map at `http://<jetson-ip>:8555` and the camera at `http://<jetson-ip>:8601`.
- `scripts/laptop_tools/로봇창열기.cmd` opens the teleop, log, and battery
  windows and both browser tabs. They use short commands in the Jetson's home
  folder (`./tele ./volt ./mem ./nav ./ask ./reloc`), which are not in this repository.
- After a run in which the objects stayed in place, `./robot/fit_detection.sh --apply cup`
  measures how often the cup was found at each distance and writes the table into
  `robot/config/depth.yaml`.

Never reinstall `torch` on the Jetson; it has its own CUDA build. Use the
package with `pip install -e . --no-deps` or `PYTHONPATH=$PWD/src`.
