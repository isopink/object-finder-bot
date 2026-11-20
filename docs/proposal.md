# Object-Finding Robot with Natural-Language Queries: Design (v4.1)

> "Where is the blue mug?" The robot searches its memory and drives to where it last saw the mug.

Version history is at the [end](#changelog).

## 1. Overview

A TurtleBot3 Waffle Pi patrols a room and remembers each object it sees on a desk as a **CLIP image embedding, a map position, and an observation time**. The user describes an object in English. The robot finds the best-matching memory by text-image similarity and navigates to it.

- **Open vocabulary**: free-form descriptions ("a red tumbler", "a black charger next to the laptop") instead of fixed classes.
- **Multimodal**: image, depth, LiDAR, and text (speech as an extension).
- **Scope**: mapping, localization, and navigation use existing packages (slam_toolbox, Nav2). The contribution is the probabilistic object memory and search.

## 2. Key decisions

| Item | Decision | Reason |
|------|----------|--------|
| Target objects | Objects on desks | Mugs, tumblers, chargers, and similar items |
| Camera mount | Raised on a mast | The stock mount is too low to see desk tops |
| Query language | English | CLIP (ViT-B/32, laion2b) is trained on English; Korean queries work poorly |
| Speech queries | Extension (Whisper, mini USB microphone) | Text input is the baseline |
| Detector | detectNet (SSD-Mobilenet-v2) vs YOLO (TensorRT), pick after comparison | Extension: NanoOWL |
| Cameras | Two supported versions, selected by `camera_mode`: `depth` (Intel RealSense, color + aligned depth) and `nodepth` (Logitech C920, color only) | Both run end to end; the C920 has no depth, so it uses bearing-only fusion |
| Object range | `depth`: RealSense depth back-projection. `nodepth`: bearing-only EKF fusion, and the observation pose is the goal while the position is uncertain | A 2D LiDAR cannot range objects on a desk |
| Compute | Jetson Xavier NX **mounted on the robot**; it runs everything (bringup, SLAM, AMCL, Nav2, vision, memory) | No camera or depth stream over Wi-Fi |
| Jetson power | **USB-C PD power bank** (20 V output) feeding the PE1000N DC input (12 to 24 V) through a PD trigger cable or a boost converter; separate from the robot battery | The robot battery (11.1 V Li-Po) cannot feed the Jetson directly, and a wall adapter tethers the robot |
| ROS 2 distro | Foxy native on the Jetson (Ubuntu 20.04), or Humble in Docker; chosen in the classroom | Must work with the robot's OpenCR firmware and TurtleBot3 packages |
| Operation | Over SSH from a laptop, long-running programs in tmux; queries typed in a terminal, video and map in a browser | No monitor or RViz in the classroom |

## 3. System

```
[TurtleBot3 Waffle Pi with the Jetson Xavier NX on board]
 LiDAR, OpenCR ──▶ turtlebot3_bringup ──▶ SLAM (slam_toolbox) / AMCL / Nav2
                                          objmem_ros: observer, finder, mapview  (ROS 2)
 RealSense or C920 ──▶ vision worker (conda, no ROS): detector + CLIP, HTTP :8600

 laptop ── SSH (tmux) ── `ask` terminal         browser: video :8554, map :8555
```

- Everything runs on the Jetson, which rides on the robot. Camera frames never cross Wi-Fi; only SSH and the browser views do.
- The ROS side (Foxy native or Humble in Docker) and the vision worker (conda Python 3.8 with CUDA PyTorch) talk over HTTP with JSON on port 8600, so the vision code does not depend on the ROS distro.
- `camera_mode: depth` uses the RealSense color and aligned depth; `camera_mode: nodepth` uses the C920 color only.

### Camera mount

- The stock camera position is too low to see desk tops, so the camera is raised on a mast.
- The camera-to-robot transform `T_base←cam` is re-measured after mounting, since height and tilt change.
- The higher center of mass limits driving speed and acceleration. If motion blurs the image, memories are recorded only while stopped.

### Modules

| Module | Input | Output | Technology |
|--------|-------|--------|------------|
| Mapping / localization | LiDAR, odometry | Occupancy grid, robot pose | slam_toolbox, AMCL |
| Detection | Color image | Bounding boxes | detectNet or YOLO (TensorRT) |
| Object position | Box, depth, robot pose | Map position + covariance | Depth back-projection, coordinate transforms |
| Object memory | Crop, position, time | Memory database | CLIP, Bayesian update, Kalman filter |
| Query | English text (speech) | Text embedding | CLIP text encoder, (Whisper) |
| Search / navigation | Query embedding | Goal pose | Similarity × confidence, Nav2 |

## 4. Probabilistic object memory

Each memory stores a position mean `μ = (x, y)` with covariance `Σ`, a CLIP image embedding `e`, the last observation time `t_last`, and an existence confidence `p` (probability the object is still there).

### 4.1 Object position (camera → map)

1. Take the **median** depth `d` near the box center: `P_c = d · K⁻¹ [u, v, 1]ᵀ`.
2. Transform to the map: `P_map = T_map←base · T_base←cam · P_c`, where `T_map←base` is the AMCL pose and `T_base←cam` is the calibrated mount transform.
3. Without depth (C920 only):
   - **Store the observation pose**: save the robot pose `(x, y, θ)` and the object's bearing, then return to that pose and re-check. No range needed.
   - **Bearing-only triangulation + EKF**: intersect sight lines from different poses and refine with an EKF as observations accumulate.
   - LiDAR range is used only for objects on the floor, since the 2D scan plane is about 20 cm above the ground.

### 4.2 Position fusion: Kalman filter

A re-observation `z` with covariance `R` (larger at longer range) updates a static-object model:

```
K = Σ (Σ + R)⁻¹
μ ← μ + K (z − μ)
Σ ← (I − K) Σ
```

Two observations are the same object when both the Mahalanobis distance and the CLIP cosine similarity pass their thresholds.

### 4.3 Existence confidence: Bayesian update with time decay

With detection rate `P(detect | present) = d` and false-positive rate `P(detect | absent) = f`:

- Location in view and **detected**: `p ← d·p / (d·p + f·(1−p))`
- Location in view and **not detected**: `p ← (1−d)·p / ((1−d)·p + (1−f)·(1−p))`
- **Time decay**: `p ← 0.5 + (p − 0.5)·exp(−Δt / τ)`, with `τ` set experimentally

The update applies only when the stored position is inside the camera's field of view and depth range, and not occluded.

### 4.4 Search score

```
s_i     = cos(CLIP_text(q), e_i)      # query-memory similarity
w_i     = softmax(s_i / T)            # normalized over candidates
score_i = w_i × p_i                   # weighted by existence confidence
```

The robot visits the top-3 candidates in order. On arrival it **re-checks the live view**: detection boxes and sliding windows are scored with CLIP against the query and a set of background prompts (softmax). A probability of 0.5 or more counts as found. Otherwise the confidence drops and the robot moves to the next candidate.

## 5. Course topics applied

| Topic | Use in this project |
|-------|---------------------|
| Linear algebra, homogeneous coordinates | Camera → robot → map transforms (4.1) |
| Probabilistic robotics | Bayesian update of object existence (4.3) |
| Motion and sensor models | Odometry model, range-dependent observation covariance `R` |
| Occupancy grid maps | Base map plus an object-memory layer |
| Kalman filter / EKF | Object position estimation (4.2) |
| Particle filter, SLAM | Mapping (slam_toolbox) and localization (AMCL) |

## 6. Schedule

| Stage | Dates | Vision / AI | Robot / navigation |
|-------|-------|-------------|--------------------|
| Jetson labs | to 10/29 | jetson-inference labs | |
| Preparation | 10/30 - 11/4 | CLIP on Jetson, YOLO TensorRT engine, RealSense depth check | SLAM and Nav2 practice in Gazebo |
| 0. Setup | 11/5 - 11/11 | detectNet vs YOLO (FPS, detection rate) | ROS 2 distro, remote link, teleop, lab map |
| 1. Memory on the map | 11/12 - 11/18 | Crop → CLIP → memory, text search (top-3), objects on the map | AMCL, Nav2 goals, camera-robot TF calibration |
| 2. Integration | 11/19 - 11/25 | Query → candidate → re-check loop, Bayesian confidence, time decay, Kalman fusion | (joint) |
| 3. Extensions | spare time | Whisper speech queries, NanoOWL comparison | Re-finding moved objects, quantitative evaluation |
| Demo / presentation | 11/26, 12/3 | | |
| Final report | 12/10 | | |

Progression shown in the report:

1. LiDAR map and robot pose
2. Fixed-class detections placed on the map
3. Free-text search with CLIP (fixed classes → open vocabulary)
4. Probabilistic memory (rejects false detections, handles moved objects)
5. Speech queries and autonomous navigation

## 7. Evaluation

- **Search success rate**: fraction of 20 queries that end within 0.5 m of the correct object (top-1 / top-3)
- **Position error**: distance between estimated and true object position (m)
- **Fixed-class detector vs CLIP search** success rate
- **With vs without probabilistic memory**: success rate after objects are moved
- **Detector comparison**: detectNet vs YOLO, FPS and detection rate on 10 test objects
- **Resources**: FPS, memory use, query latency (`jtop`)

## 8. Demo scenario

1. The robot patrols the lab and records the objects on the desks.
2. "Where is the blue mug?" The robot drives to the mug.
3. The user moves the mug.
4. Same query: the robot goes to the old location, finds nothing, lowers the confidence, tries the next candidate, and updates the new location.
5. Descriptive queries: "a black charger next to the laptop", "a plastic cup with a straw".

## 9. Equipment and software

- TurtleBot3 Waffle Pi (LDS-02 LiDAR, OpenCR; no Raspberry Pi, the OpenCR and LiDAR connect to the Jetson over USB)
- NVIDIA Jetson Xavier NX (ASUS PE1000N, 8 GB, 256 GB SSD)
- USB-C PD power bank (20 V) with a PD trigger cable or boost converter, for the Jetson
- Logitech C920 webcam, Intel RealSense depth camera, camera mast
- Mini USB microphone, plug-and-play (speech queries)
- 10 test objects, 20 query sentences with ground-truth positions

Software:

- Jetson: Ubuntu 20.04, JetPack 5.1.5, PyTorch 2.1, OpenCV (CUDA)
- jetson-inference (detectNet), OpenCLIP ViT-B/32 (laion2b, FP16); extensions: Whisper, NanoOWL
- ROS 2: TurtleBot3, slam_toolbox, Nav2 (AMCL), realsense2_camera
  - Waffle Pi on Foxy: run Foxy natively on the Jetson (Ubuntu 20.04)
  - Waffle Pi on Humble: run Humble on the Jetson in Docker (NVIDIA container runtime)

### Development workflow

The Jetson and the robot are reachable only on the lab network, so development happens off-site and the lab is used for verification. In the lab, the team logs in to the Jetson over SSH and runs each step from a script in `robot/`.

```
develop → push → git pull on the Jetson (SSH) → run robot/check_stageN.sh → scp logs and rosbags back → analyze off-site
```

- Keep code changes in the lab minimal. Bring back logs and rosbags instead.
- Each verification runs from a single script (`robot/check_stage1.sh` to `robot/check_stage5.sh`).
- Maps, calibration values, and TensorRT engines can only be produced on the hardware, so they are saved as files.
- TensorRT engines are built on the Jetson. Engines built on a laptop do not work.
- Large files (model weights, rosbags) are kept out of Git.

## 10. Risks

| Risk | Mitigation |
|------|------------|
| ROS 2 distro mismatch (Waffle Pi vs Jetson) | Check `ROS_DISTRO` first, then unify (Docker on the Jetson if needed) |
| Jetson power and weight on the robot | PD power bank for the Jetson; measure its runtime with everything running early; keep the vision rate at 1 to 2 Hz |
| Wi-Fi or SSH drops during a run | Everything runs on the robot; programs run in tmux, so an SSH drop does not stop them |
| 8 GB memory limit on the Jetson, shared with SLAM and Nav2 | TensorRT / FP16, run CLIP only on detections, load Whisper only for queries |
| RealSense unavailable | `camera_mode: nodepth` with the C920: bearing-only EKF, observation-pose revisit |
| Raised camera: vibration and center of mass | Rigid mast, speed and acceleration limits, record memories while stopped |
| Camera-robot calibration error | Allocate calibration time early; Kalman fusion averages repeated observations |
| CLIP window search unstable on small objects | Move closer before re-checking, add smaller windows, (extension) NanoOWL |
| Detector false positives and misses | Compare detectNet and YOLO; CLIP re-check as a second stage |
| Inaccurate speech recognition | Fall back to text input |
| Unstable autonomous navigation | Teleoperated patrol for the memory phase |

## 11. Possible extensions

- NanoOWL: text → bounding box directly, replacing window cropping
- Remote monitoring dashboard (WebRTC / GStreamer)
- Change report: "What changed?"
- Relational queries: "What is on the desk?"

## Open items

- [x] ROS 2 distro on the Waffle Pi: Foxy native on the Jetson (2026-11-18)
- [x] Waffle Pi LiDAR model: LDS-02 (2026-11-18)
- [ ] LiDAR position on the top plate (the Jetson box blocks part of the scan)
- [ ] Camera mount height and tilt, mast fixture
- [ ] Camera used in the demo: RealSense (`depth`) or C920 (`nodepth`)
- [x] Jetson power on the robot: PD power bank (2026-11-20)
- [ ] Power bank model, trigger cable or boost converter, and runtime with everything running

## References

1. D. Franklin, *jetson-inference: Hello AI World guide to deploying deep-learning inference networks and deep vision primitives with TensorRT and NVIDIA Jetson*, GitHub. https://github.com/dusty-nv/jetson-inference
2. A. Radford et al., "Learning Transferable Visual Models From Natural Language Supervision," ICML, 2021.
3. OpenCLIP, GitHub. https://github.com/mlfoundations/open_clip
4. B. Chen et al., "Open-vocabulary Queryable Scene Representations for Real World Planning," ICRA, 2023.
5. S. Thrun, W. Burgard, D. Fox, *Probabilistic Robotics*, MIT Press, 2005.

## Changelog

### v4.1 (2026-11-20)

| Item | v4 | v4.1 |
|------|----|------|
| Jetson power | Not specified (v3 said "no extra battery") | **PD power bank** for the Jetson, separate from the robot battery |
| Hardware | Raspberry Pi listed, LiDAR model unknown | No Raspberry Pi; LDS-02 LiDAR; Foxy native (seen on 2026-11-18) |

### v4 (2026-11-16)

| Item | v3 | v4 |
|------|----|----|
| Compute | Jetson off-board over Wi-Fi | **Jetson mounted on the robot**; it runs bringup, SLAM, AMCL, Nav2, vision, and memory |
| Cameras | C920 + RealSense | **Both versions supported end to end**, selected by `camera_mode` (`depth` / `nodepth`) |
| Position without depth | Fallback | Bearing-only EKF fusion; the observation pose is the goal while the position is uncertain |
| Operation | Not specified | **Over SSH**, programs in tmux, queries in a terminal, video and map in a browser |
| ROS 2 distro | Match the Waffle Pi | Foxy native or Humble in Docker, chosen in the classroom |
| Code | `slam/`, `vision/` scripts | `objmem` package, `ros/objmem_ros`, `robot/` scripts, rewritten `vision/` |

### v3 (2026-11-16)

| Item | v2 | v3 |
|------|----|----|
| Target objects | Not specified | **Objects on desks** |
| Camera mount | Stock position | **Raised on a mast** |
| Query language | English | English (confirmed; Korean queries work poorly with CLIP) |
| Microphone | Availability unknown | **Mini USB microphone** added |
| Compute | Off-board first, on-board fallback with a battery | **Off-board only**, no extra battery |

### v2 (2026-10-29)

| Item | v1 | v2 |
|------|----|----|
| Detector | YOLO (TensorRT) | detectNet baseline, compared against YOLO |
| Query language | Korean speech | English |
| Speech queries | Required | Extension |
| Cameras | Pi camera / C920 | C920 + RealSense |
| Object range | Camera-LiDAR calibration | RealSense depth; fallback: observation pose, bearing-only triangulation |
| Compute | On-board feasibility unknown | Off-board first, on-board fallback |
| Probabilistic memory | Concept only | Bayesian update, time decay, Kalman fusion, and search score specified |
| Evaluation | 5 metrics | Added detector comparison, off-board vs on-board latency, 0.5 m success criterion |
