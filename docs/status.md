# Status

What has been verified without the robot, and what must still be checked in
the classroom. Nothing in this repository has run on the real robot yet.

Last update: 2026-11-16, integration of the eight work branches into `main`.

## Summary

| Area | Code | Verified here | Still to verify on the robot |
|---|---|---|---|
| Shared types and config | `src/objmem/types.py`, `config/default.yaml` | `pytest tests/test_types.py` | Tuned values (`d`, `f`, `tau`, gates, `found_thresh`) |
| Object memory | `src/objmem/memory.py` | Hand-computed Kalman, EKF, Bayes, decay tests | Thresholds on real detections |
| Geometry (both camera modes) | `src/objmem/geometry.py`, `bearing.py` | Reprojection, covariance, mount, nodepth convergence through the memory | Mount signs and intrinsics (stage 4, "Camera mount") |
| Search loop | `src/objmem/search.py` | Fake and real memory, all failure paths, JSON-lines log | Real Nav2 and the real re-check |
| Speech | `src/objmem/speech.py` | `arecord` and Whisper mocked | USB microphone, Whisper on the Jetson |
| Vision core and worker | `embed.py`, `crops.py`, `verify.py`, `worker.py`, `fakes.py`, `scripts/vision_worker.py` | Crop geometry, re-check softmax, HTTP round trip in both modes | CLIP on CUDA, latency, `found_thresh` on real photos |
| Jetson adapters | `detectors.py`, `camera.py`, `vision/` | Adapters against mocked `jetson_inference`, `jetson_utils`, `pyrealsense2`, `ultralytics`, `cv2` | Every real library call |
| Toy world, evaluation, map drawing | `src/objmem/sim/`, `viz.py`, `scripts/demo_offline.py`, `scripts/evaluate.py` | Demo and evaluation below, deterministic | `evaluate.py` on a real memory file and search log |
| ROS 2 nodes | `ros/objmem_ros/` | `core.py` unit tests here; `colcon build` and end-to-end tests in CI on Foxy and Humble | Real TF, AMCL, Nav2, camera topics |
| Robot scripts | `robot/` | `bash -n` (in `pytest`), `shellcheck` by the author | Every script (no ROS, robot, or Docker here) |

## Verified here (Windows PC, Python 3.13, no GPU, no ROS)

All commands run from the repository root after `pip install -e ".[dev]"`.

| Command | Result |
|---|---|
| `pytest` | 373 passed (includes `ros/objmem_ros/test`, the Python 3.8 syntax check of every `.py`, and `bash -n` on every `.sh`) |
| `python scripts/demo_offline.py --camera depth` | Mug found (0.03 m off); after the move, old place fails (p 0.92 -> 0.70), new place found (0.01 m off) |
| `python scripts/demo_offline.py --camera nodepth` | Same story with bearing-only fusion (0.00 m and 0.01 m off) |
| `python scripts/evaluate.py` | Tables below |
| `python scripts/vision_worker.py --fake` + `VisionClient` | All four endpoints in both camera modes (output below) |
| `python vision/find_object.py --fake --output none` | Commands `s t l q f exit` work (Session 8) |
| `--help` of every script in `scripts/`, `vision/`, `robot/lib/` | Starts on a PC; every flag used in the docs and scripts exists |

CI (GitHub Actions):

| Workflow | Jobs | What it runs |
|---|---|---|
| `tests.yml` | Python 3.8, Python 3.10 (ubuntu-22.04) | `pip install -e ".[dev]"`, `pytest` |
| `ros.yml` | `ros:foxy`, `ros:humble` containers | `colcon build`, ROS-free unit tests, finder end to end (fake worker + fake `navigate_to_pose`: goal sent, re-check fails, next goal, re-check succeeds), launch-file smoke test (observer, mapview HTTP, markers, memory saved on Ctrl-C) |

CI status at integration: see "CI result" at the end of this file.

### Evaluation (toy world, `python scripts/evaluate.py`)

5 seeds x 20 queries per row; success = re-check passed and position within 0.5 m.

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

The toy world is easier than the classroom (perfect localization, no
occlusion, synthetic embeddings): the comparisons matter, not the absolute
numbers. The 5 % CLIP failures are "Where is my phone charger?", which ranks
the phone first.

### Fake worker round trip

```
== depth
health       {'ok': True, 'camera': True, 'camera_mode': 'depth'}
detect_embed [('cup', (96, 192, 192, 336), 1.2, 512), ('book', (352, 216, 544, 360), 2.0, 512)]
verify red   (True, 1.0)
verify plant (False, 2.4e-14)
embed_text   (512,)
== nodepth
health       {'ok': True, 'camera': True, 'camera_mode': 'nodepth'}
detect_embed [('cup', (96, 192, 192, 336), None, 512), ('book', (352, 216, 544, 360), None, 512)]
```

## To verify in the classroom (order of `robot/README.md`)

### Stage 0: install

- [ ] Foxy from apt on the Jetson (`./robot/install_foxy_jetson.sh`). Foxy is
  end-of-life; if packages are gone, `OFB_FOXY_SNAPSHOT=1` uses
  `snapshots.ros.org/foxy/final` (untested).
- [ ] The LDS-02 driver (`ld08_driver`) source build and its branch name.
- [ ] Or Humble in Docker: the arm64 image build; `ros-humble-ld08-driver` and
  `realsense2_camera` on arm64 are optional in the Dockerfile.
- [ ] `objmem_ros` builds (`./robot/build_ws.sh`); the ROS Python has
  `python3-numpy python3-yaml python3-pil`.
- [ ] Python 3.8 in conda env `test1001` imports `objmem` (`pip install -e . --no-deps`
  or `PYTHONPATH`); never reinstall torch.

### Stage 1: bringup and teleop

- [ ] OpenCR firmware matches ROS 2 (`robot/README.md`, "OpenCR firmware").
- [ ] `LDS_MODEL` (LDS-01 or LDS-02), `/scan`, `/odom`, `/tf` arrive.

### Stage 2: SLAM and a saved map

- [ ] `slam_toolbox` map of the room, `save_map.sh`, `lib/map_info.py` stats.
- [ ] Foxy `ros2 bag play` has no `--clock` (handled: replay uses wall time on Foxy).

### Stage 3: localization and one Nav2 goal

- [ ] `set_initial_pose.sh`, AMCL covariance parsing, `goto.sh` result parsing.
- [ ] The Nav2 params file path `turtlebot3_navigation2/param[/<distro>]/waffle_pi.yaml`.
- [ ] Driving with the raised camera mast at `OFB_MAX_VEL` (0.15 m/s default).

### Stage 4: camera and vision worker, both versions

- [ ] RealSense: `pyrealsense2` streams, depth aligned to color, depth in meters
  (z-depth, which `geometry.observe` assumes).
- [ ] C920: `jetson_utils.videoSource`, OpenCV fallback, the device number
  (`scripts/vision_worker.py --camera-device /dev/videoN`).
- [ ] `ClipEmbedder` on CUDA with FP16; `/detect_embed` and `/verify` latency
  (83 windows + detections in batches of 32); GPU memory next to the detector.
- [ ] detectNet and YOLO (`--detector yolo --yolo-engine <file>`): `vision/bench_detector.py`.
- [ ] Camera intrinsics (`vision/print_intrinsics.py`) and `hfov` written to
  `robot/config/<mode>.yaml`.
- [ ] `found_thresh` on classroom photos: `scripts/tune_verify.py`.

### Camera mount

- [ ] Measure `cam_x cam_y cam_z cam_yaw cam_pitch` and check the sign
  conventions with a cup 1.0 m ahead (map view). Conventions in code: optical
  frame x right, y down, z forward; positive `cam_pitch` tilts down; positive
  `cam_yaw` turns left.

### Stage 5: the full loop

- [ ] `start_all.sh <map> depth` and `nodepth`: tmux panes start, conda
  activates in the worker pane.
- [ ] Observer: TF `map -> base_link`, 1 Hz, observes only while stopped;
  memory saved periodically and on Ctrl-C.
- [ ] Finder: real Nav2 goals, timeout and cancel while driving, re-check on
  arrival, `/objmem/status` lines in the `ask` pane, `result:` line.
- [ ] `image_source:=ros` with the RealSense topics (only unit-tested).
- [ ] Mapview at port 8555 with the real `map_saver` map; `/objmem/markers`.
- [ ] Memory thresholds on real data: `cos_thresh = 0.8` (image-image cosine
  across views) and `maha_thresh` are guesses; occlusion is not modeled.
- [ ] `ask --voice`: USB microphone as the ALSA device (`mic_device`), the
  silence threshold (`WhisperSTT(silence_rms=...)`), Whisper `base.en` memory.
  Install Whisper with `pip install --no-deps openai-whisper` and then
  `pip install tiktoken more-itertools numba tqdm`.
- [ ] Jetson power on the robot (PD power bank, decided 2026-11-20): runtime
  with everything running.

### Evaluation on the robot

- [ ] Measure object positions into `data/ground_truth.yaml`, run the 20
  queries of `data/queries.yaml`, then
  `python scripts/evaluate.py --memory robot/memory/<map>_<mode>.npz --log robot/memory/search_<map>_<mode>.jsonl --ground-truth data/ground_truth.yaml --map robot/maps/<map>.yaml`.

## Changes made during integration

Contract changes requested by the sessions and applied (`types.py`,
`config/default.yaml`, `tests/test_types.py` kept consistent):

| Change | Requested by | Why |
|---|---|---|
| `hfov: 1.2 -> 0.96` | Session 4 | 1.2 rad does not match `fx = 615`, `img_w = 640` (`2 atan(320/615) = 0.96`); with 1.2, objects outside the image got negative Bayes updates |
| `search_log: ""` | Session 7 | Path of the JSON-lines search log read by `evaluate.py` |
| `whisper_model: base.en`, `mic_device: ""` | Session 7 | Configure `ask --voice` from the YAML (`ask --voice --config <yaml>`) |

Fixes between sessions:

- `getattr(params, ...)` fallbacks removed for fields that now exist (`geometry`, `search`).
- `objmem_ros.compat` imports the real `ObjectMemory`, `geometry`, `search`,
  `worker`, and `viz`; the stand-ins and their tests are gone. Only a plain
  PNG drawing remains for a ROS Python without PIL.
- `viz.draw_map` labels: catch `ValueError` from `textbbox` with Pillow 8-9
  and the bitmap font (Ubuntu 22.04 apt Pillow 9.0.1; seen in the Humble CI log).
- `robot/objmem.sh` now passes `search_log`, `map_yaml`, and `worker_url` to the
  launch file, so the search log the classroom guide promises is written and
  mapview draws the saved map.
- `scripts/vision_worker.py`: `--camera-device`, `--threshold`, `--yolo-model`,
  `--yolo-engine` passed through to `make_camera` / `make_detector` (Session 8).
- `pytest` also runs `ros/objmem_ros/test` (ROS-free); `out/` is git-ignored.
- `tests/test_geometry.py` derives the in-view edge from `params.hfov`.
- Docs that pointed at `slam/` and the old `vision/` files now point at
  `robot/` and the new `vision/`. `slam/`, `vision/jetson_find_object.py`, and
  `vision/clip_jetson_test.py` are gone.

Tests added during integration: `tests/test_integration.py` (toy world through
the real modules in both camera modes: patrol -> query -> found within 0.5 m,
the moved-object scenario, and `search.find` with `ClientVerifier` against the
fake worker on a free port), `tests/test_py38_syntax.py`,
`tests/test_shell_syntax.py`, `tests/test_worker_flags.py`.

## Behavior notes from the sessions

- Memory: decay is lazy per item and never applied twice for the same interval;
  nothing is deleted automatically (`ObjectMemory.remove(id)` exists); a moved
  object's old memory drifts back toward 0.5 over `tau` unless it is seen empty
  again. The memory is thread-safe (the observer and the finder share it in one
  process).
- Search: `find` retries `view_pose` after any failed goal; an exception from
  the verifier counts as `not_found` without lowering p; `nav_failed` never
  changes the memory. Final status `not_found` if any candidate was re-checked,
  `nav_failed` if none could be reached.
- Worker: one request at a time; `/detect_embed` embeds 3x3 tiles when the
  detector finds nothing; errors come back as JSON with 400 / 404 / 503 / 500.
- `vision/find_object.py` converts the C920 frame CUDA -> numpy -> CUDA; use
  `--width 1280 --height 720` if 1080p is slow.
- Possible later change: an `Observation.origin` (camera position) for the
  bearing EKF; the error it removes is below half of `sigma_bearing`.

## CI result

On `main` after the integration merge (GitHub Actions, 2026-11-16):

| Workflow | Job | Result |
|---|---|---|
| `tests.yml` | Python 3.8 | passed (373 tests) |
| `tests.yml` | Python 3.10 | passed (373 tests) |
| `ros.yml` | `ros:foxy` | passed: `colcon build`, 28 unit tests, `E2E PASSED`, `LAUNCH SMOKE PASSED`, no stand-ins |
| `ros.yml` | `ros:humble` | passed: same steps; no `draw_map` fallback warning after the Pillow fix |

Check the current state with `gh run list --branch main`.
