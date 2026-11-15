# Object-Finding Robot with Natural-Language Queries

> "Where is the blue mug?" The robot searches its memory and drives to where it last saw the mug.

A TurtleBot3 Waffle Pi patrols a room and remembers the objects it sees on desks as a **CLIP embedding, a map position, and a timestamp**. Given an English description, it finds the best-matching memory by text-image similarity and navigates there.

Course project for Intelligent Robotics at the University of Seoul (Fall 2026).

## Core idea: probabilistic object memory

Unlike a fixed-class detector, the robot is queried with free-form descriptions such as "a red tumbler" or "a black charger next to the laptop" (open vocabulary). Each memory holds:

| Field | Update |
|-------|--------|
| Position mean `μ = (x, y)` and covariance `Σ` | Fused with a **Kalman filter** on every re-observation |
| CLIP image embedding `e` | Extracted from the object crop (OpenCLIP ViT-B/32, FP16) |
| Existence confidence `p` | **Bayesian update** on seen / not seen, plus time decay |
| Last-seen time `t_last` | Drives the time decay |

Search score = `softmax(query-memory similarity) × existence confidence`. The robot visits the top candidates in order and re-checks the live view on arrival. On a miss it lowers the confidence and moves to the next candidate.

Equations and design rationale: [docs/proposal.md](docs/proposal.md).

## System

```
[Waffle Pi (Raspberry Pi)]                      [Jetson Xavier NX (remote)]
 LiDAR ───────────────┐                        ┌─ SLAM (slam_toolbox) / AMCL / Nav2
 Odometry ────────────┤                        ├─ Object detection (detectNet / YOLO, TensorRT)
 C920 (compressed) ───┼── ROS 2 over Wi-Fi ──▶ ├─ Object range from RealSense depth
 RealSense (depth) ───┘                        ├─ CLIP embedding (FP16)
 Motor control ◀────────────────────────────── ├─ Probabilistic object memory
                                               └─ Query: English text (+ Whisper speech)
```

| Module | Technology |
|--------|------------|
| Mapping, localization, navigation | slam_toolbox, AMCL (particle filter), Nav2 |
| Object detection | detectNet (SSD-Mobilenet-v2) or YOLO (TensorRT) |
| Object position | Depth back-projection, camera → base_link → map transform |
| Object memory and search | CLIP, Kalman filter, Bayesian update |

Mapping, localization, and navigation use existing packages. The project's contribution is the object memory and search module.

## Hardware

- TurtleBot3 Waffle Pi (LiDAR, OpenCR, Raspberry Pi)
- NVIDIA Jetson Xavier NX (ASUS PE1000N, 8 GB), Ubuntu 20.04, JetPack 5.1.5
- Logitech C920 webcam and Intel RealSense depth camera
- Camera mast: the stock camera height is too low to see desk tops, so the camera is mounted higher

## Repository

| Path | Contents |
|------|----------|
| [`slam/`](slam/README.md) | ROS 2 SLAM scripts: Gazebo simulation, real-robot verification, rosbag record/replay, map saving |
| [`vision/`](vision/) | Jetson vision code: CLIP speed and memory benchmark, camera + detectNet + CLIP memory/search |
| [`docs/proposal.md`](docs/proposal.md) | Design document: equations, schedule, evaluation metrics, risks |

## Usage

### Mapping (`slam/`)

The same scripts run against Gazebo and the real robot. See [`slam/README.md`](slam/README.md) for setup.

```bash
cd slam
./scripts/sim_slam.sh slam_toolbox world      # Gazebo + SLAM + RViz
./scripts/save_map.sh sim_world_toolbox       # save the map
```

### Object memory and search (`vision/`)

Runs the vision part on a Jetson and a camera, without the robot. Memories store an on-screen box instead of a map coordinate.

```bash
cd vision
python clip_jetson_test.py --fp16     # CLIP latency and GPU memory
python jetson_find_object.py          # video at http://<JETSON_IP>:8554
```

| Command | Action |
|---------|--------|
| `s` | Remember the objects detected in the current frame |
| `t` | Remember the frame as 3x3 tiles (for objects the detector does not know) |
| `q a black bag` | Find the closest match in memory |
| `f a black bag` | Search the current frame directly |

## Status

| Stage | Scope | Code |
|-------|-------|------|
| Mapping | SLAM scripts (simulation, real-robot verification, rosbag) | `slam/` |
| Vision | CLIP on Jetson, screen-space memory and search | `vision/` |
| Memory on the map | Project objects to map coordinates, AMCL and Nav2 navigation | In progress |
| Integration | Query → drive to candidate → re-check loop, probabilistic updates | Planned |
| Extensions | Whisper speech queries, re-finding moved objects | Planned |
