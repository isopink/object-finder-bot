# Object-Finding Robot with Natural-Language Queries

> "Where is the blue mug?" The robot searches its memory and drives to where it last saw the mug.

A TurtleBot3 Waffle Pi patrols a room and remembers the objects it sees on desks
as a **CLIP embedding, a map position, a timestamp, and an existence
confidence**. Given an English description, it picks the best memory, drives
there with Nav2, and re-checks the live camera view. If the object is gone, the
confidence drops and the robot tries the next candidate.

Course project for Intelligent Robotics at the University of Seoul (Fall 2026).
Design and equations: [docs/proposal.md](docs/proposal.md). What has been
verified and what is still to check on the robot: [docs/status.md](docs/status.md).

## How it works

Everything runs on the Jetson Xavier NX mounted on the robot. The team works
over SSH from a laptop: queries are typed in a terminal, video and the map are
viewed in a browser.

```
Jetson Xavier NX (on the robot)
 ├─ robot bringup      turtlebot3_bringup (OpenCR, LiDAR)
 ├─ ROS 2 side         slam_toolbox / AMCL / Nav2, objmem_ros nodes
 │                     (Foxy native, or Humble in Docker)
 └─ vision worker      conda Python 3.8, no ROS: camera + detector + CLIP
                       HTTP JSON server on port 8600
```

| Port | What |
|------|------|
| 8554 | WebRTC video (`vision/find_object.py`) |
| 8555 | Map view with remembered objects (`mapview` node) |
| 8600 | Vision worker (`scripts/vision_worker.py`) |

Each memory holds a position mean and covariance, a CLIP image embedding, the
last-seen time, and an existence confidence `p`:

| Field | Update |
|-------|--------|
| Position `μ`, `Σ` | Kalman update with depth (RealSense); EKF bearing update without depth (C920) |
| Embedding `e` | Running mean of the CLIP crop embeddings |
| Confidence `p` | Bayes update on seen / not seen while in view, time decay toward 0.5 |

Search score = `softmax(cos(text, e) / T) × p`. The robot visits the top 3 in
order and re-checks the live view with CLIP against background prompts.

Two camera versions are supported end to end, selected by `camera_mode` in
`config/default.yaml`: `depth` (Intel RealSense, color + aligned depth) and
`nodepth` (Logitech C920, color only).

## Repository

| Path | Contents |
|------|----------|
| `src/objmem/` | The Python package (no ROS): memory, geometry, search, vision, toy world |
| `config/default.yaml` | Every tunable value. In the classroom edit this file, not the code |
| `scripts/` | `vision_worker.py`, `demo_offline.py`, `evaluate.py`, `tune_verify.py` |
| `ros/objmem_ros/` | ROS 2 package: `observer`, `finder`, `mapview`, `ask`, launch file ([ros/README.md](ros/README.md)) |
| `robot/` | Bash scripts for the Jetson on the robot, one per step ([robot/README.md](robot/README.md)) |
| `vision/` | Camera-only demo and benchmarks for the Jetson ([vision/README.md](vision/README.md)) |
| `data/` | Query set and ground-truth template for the evaluation |
| `tests/` | `pytest` suite, runs on a PC with fakes |
| `docs/` | Design document, status, jetson-inference notes |

Package modules:

| Module | Role |
|--------|------|
| `objmem.types` | Shared data types, `Params`, interfaces |
| `objmem.memory` | `ObjectMemory`: association, Kalman / EKF fusion, Bayes update, decay, save/load |
| `objmem.geometry`, `objmem.bearing` | Detection + robot pose -> map position and covariance |
| `objmem.search` | Query -> candidates -> drive -> re-check loop |
| `objmem.embed`, `crops`, `verify` | CLIP embedder, crop generators, live re-check |
| `objmem.worker` | Vision worker HTTP server and client |
| `objmem.detectors`, `objmem.camera` | detectNet / YOLO and RealSense / C920 adapters |
| `objmem.speech` | Whisper speech queries (extension) |
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

Follow [robot/README.md](robot/README.md) stage by stage. It says what to plug
in, what to type, what the output should look like, and what to copy back.

The first three commands on the Jetson (over SSH):

```bash
cd ~/object-finder-bot && git pull
source robot/env.sh
bash robot/check_stage1.sh
```

Never reinstall `torch` on the Jetson; it has its own CUDA build. Use the
package with `pip install -e . --no-deps` or `PYTHONPATH=$PWD/src`.
