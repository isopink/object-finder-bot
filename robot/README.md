# Classroom guide: running the robot

Everything runs on the Jetson Xavier NX mounted on the TurtleBot3 Waffle Pi:
robot bringup, SLAM, AMCL, Nav2, the vision worker, and the object memory. You
work from a laptop over SSH. There is no monitor and no RViz: queries are typed
in a terminal, the map is viewed in a browser, and long-running programs run
in tmux.

Work through the stages in order. Each stage has one check script. Every
check prints `[OK]` / `[FAIL]` lines; each `[FAIL]` is followed by a `hint:`
line that says what to look at. Every script writes a log to
`robot/logs/<timestamp>/`. Copy those folders back to the laptop (`scp`, shown
at the end of each stage) so problems can be studied after class.

| Stage | Goal | Check |
|---|---|---|
| 0 | Install (once) | `install_foxy_jetson.sh` or `docker/run.sh build` |
| 1 | Bringup and teleop | `check_stage1.sh` |
| 2 | SLAM and a saved map | `check_stage2.sh <map>` |
| 3 | Localization and one Nav2 goal | `check_stage3.sh` |
| 4 | Camera and vision worker, both camera versions | `check_stage4.sh depth`, `check_stage4.sh nodepth` |
| 5 | Full loop: observe, query, drive, re-check | `start_all.sh <map> <mode>`, `check_stage5.sh` |

## Scripts

| Script | What it does |
|---|---|
| `env.sh` | Shared settings (sourced by every script; values can be overridden by env vars) |
| `install_foxy_jetson.sh [--with-cameras]` | ROS 2 Foxy + TurtleBot3 + slam_toolbox + Nav2 + rosbag2 + tmux + udev rules |
| `docker/run.sh build` / `docker/run.sh` | Humble image, or a shell in the Humble container |
| `build_ws.sh` | Build `ros/objmem_ros` with colcon (again after a `git pull` that changes `ros/`) |
| `bringup.sh` | OpenCR (motors, odometry, IMU) and LiDAR |
| `teleop.sh` | Keyboard driving over SSH |
| `slam.sh [slam_toolbox\|cartographer]` | Mapping |
| `save_map.sh <name>` | Save the map to `robot/maps/<name>.pgm/.yaml` |
| `nav.sh <map>` | AMCL + Nav2 on a saved map (speed capped at `OFB_MAX_VEL`, default 0.15 m/s) |
| `set_initial_pose.sh x y yaw` | Tell AMCL where the robot is (replaces RViz "2D Pose Estimate") |
| `goto.sh x y yaw` / `goto.sh --ahead 0.5` | Send one Nav2 goal and wait for the result |
| `record.sh [--camera]` / `replay.sh <bag>` | Record sensors to `robot/bags/`, replay (optionally with SLAM) |
| `worker.sh depth\|nodepth [--fake]` | Vision worker in the conda env (port 8600) |
| `camera_ros.sh depth\|nodepth` | ROS camera node, only for `OFB_IMAGE_SOURCE=ros` |
| `objmem.sh <map> depth\|nodepth` | Waits for Nav2 and the worker, sets the initial pose, launches `objmem.launch.py` |
| `start_all.sh <map> [depth\|nodepth]` / `stop_all.sh` | Everything in one tmux session `ofb` |
| `check_stage1.sh` ... `check_stage5.sh` | Stage checks |

Settings you may need to change (export before running, or add to `~/.bashrc`
after the `source .../robot/env.sh` line):

| Variable | Default | When to change |
|---|---|---|
| `LDS_MODEL` | `LDS-02` | Sticker on the LiDAR says LDS-01 |
| `ROS_DOMAIN_ID` | `30` | Another team uses 30 |
| `ROS_LOCALHOST_ONLY` | `1` | Set `0` only to see topics from a laptop with ROS |
| `OPENCR_PORT`, `LIDAR_PORT` | `/dev/ttyACM0`, `/dev/ttyUSB0` | The devices enumerate differently |
| `ROS_DISTRO` | auto (`/opt/ros/*`, else Docker Humble) | Force one |
| `OFB_DETECTOR` | `detectnet` | `yolo`, or `owl` (NanoOWL: finds clear bottles and boxes that detectNet misses; needs `~/nanoowl` and its engine, see `vision/README.md`) |
| `OFB_IMAGE_SOURCE` | `worker` | `ros` if the camera must be a ROS node |
| `OFB_CONDA_ENV` | `test1001` | Different conda env name |
| `OFB_MAX_VEL` | `0.15` | Faster or slower Nav2 driving (m/s) |
| `OFB_INIT_POSE` | `0 0 0` | Robot does not start where mapping started (`"x y yaw"`, or `skip`) |

### tmux in 30 seconds

```bash
tmux new -s work            # new session (or: tmux attach -t work)
# Ctrl+B "   split top/bottom      Ctrl+B %   split left/right
# Ctrl+B arrow   move between panes    Ctrl+B z   zoom a pane in/out
# Ctrl+B d   detach (programs keep running; SSH can drop safely)
tmux attach -t ofb          # the session start_all.sh creates
```

Always start long-running scripts (`bringup.sh`, `slam.sh`, `nav.sh`,
`worker.sh`) inside tmux, so a dropped Wi-Fi connection does not kill them.

## Stage 0: install (once)

On the laptop:

```bash
ssh <user>@<jetson-ip>
```

On the Jetson:

```bash
git clone https://github.com/isopink/object-finder-bot.git ~/object-finder-bot   # first time
cd ~/object-finder-bot && git pull
```

Which ROS? The Jetson runs Ubuntu 20.04, so:

- **Foxy native (try this first).** `./robot/install_foxy_jetson.sh`
  (10-30 min). It installs ROS packages from apt, builds the LDS-02 driver,
  installs the udev rules, adds `source ~/object-finder-bot/robot/env.sh` to
  `~/.bashrc`, and builds `objmem_ros`. It never touches conda or PyTorch.
  Run it with no conda env active (`conda deactivate`).
- **Humble in Docker** (if Foxy cannot be used): install the udev rules on the
  host, then build the image (20-40 min):

  ```bash
  sudo cp robot/udev/99-ofb-robot.rules /etc/udev/rules.d/ && sudo udevadm control --reload-rules && sudo udevadm trigger
  ./robot/docker/run.sh build
  ./robot/build_ws.sh            # builds objmem_ros inside the container
  echo "source $HOME/object-finder-bot/robot/env.sh" >> ~/.bashrc
  ```

  With no `/opt/ros` on the host, every ROS script re-runs itself inside the
  container (`ofb-humble`, host network, `/dev` shared, repo mounted at the
  same path). `./robot/docker/run.sh` opens a shell there. The vision worker
  always stays on the host in conda.

Expected: the install ends with `[OK] all checks passed`. Open a new SSH
session (or `source ~/.bashrc`), then go to stage 1.

If `install_foxy_jetson.sh` says `ros-foxy-ros-base not found` (Foxy is
end-of-life and may leave the main repository), run
`OFB_FOXY_SNAPSHOT=1 ./robot/install_foxy_jetson.sh`.

Copy back: `scp -r <user>@<jetson-ip>:~/object-finder-bot/robot/logs ./`

## Stage 1: bringup and teleop

Plug in: OpenCR micro-USB to the Jetson, LiDAR USB adapter to the Jetson,
charged battery, robot power switch ON. Put the robot on the floor with about
1 m of free space around it (the check turns it in place).

```bash
tmux new -s work
./robot/bringup.sh                    # pane 1: wait for "Run!" / no errors
./robot/check_stage1.sh               # pane 2 (Ctrl+B ")
./robot/teleop.sh                     # pane 2, afterwards: drive a little, s to stop
```

Expected from `check_stage1.sh`:

```
== 1. USB devices (lsusb)
  [OK]   OpenCR (0483:5740)
  [OK]   LiDAR USB adapter (10c4:ea60)
...
  [OK]   /scan at 5.0 Hz
  [OK]   battery 12.1 V
  [OK]   robot turned 51 deg (odometry follows /cmd_vel)
[OK] all checks passed
```

If it fails:

| Symptom | Check |
|---|---|
| OpenCR or LiDAR not on USB | Cables, power switch, `lsusb` |
| `/dev/ttyACM0` no permission | udev rules (stage 0), or `sudo usermod -aG dialout $USER` and log in again |
| bringup: `Failed connection with Devices` | OpenCR firmware is not the ROS 2 firmware: see "OpenCR firmware" below |
| No `/scan` | `LDS_MODEL` matches the sticker; LDS-02 needs `ld08_driver` (`ros2 pkg prefix ld08_driver`) |
| `/odom` OK but robot does not turn | Wheels touching the floor, battery, OpenCR power switch |
| Nothing at all in `ros2 topic list` | Same `ROS_DOMAIN_ID` in every pane (`echo $ROS_DOMAIN_ID`), conda env active (`conda deactivate`) |

Copy back: `scp -r <user>@<jetson-ip>:~/object-finder-bot/robot/logs ./`

Optional: record raw sensor data for later (`./robot/record.sh`, drive with
teleop, Ctrl+C). The bag lands in `robot/bags/<timestamp>/`; copy it with
`scp -r`.

## Stage 2: SLAM and a saved map

Keep `bringup.sh` running.

```bash
./robot/slam.sh                       # pane 2
./robot/teleop.sh                     # pane 3: drive the whole room slowly
./robot/check_stage2.sh room429       # pane 4, any time: saves the map and prints its size
```

Drive slowly, turn in short steps, and come back to the start once so SLAM
closes the loop. Run `check_stage2.sh room429` (or `save_map.sh room429`)
several times while mapping; each run overwrites the map and keeps the
previous one as `room429.bak.*`. When done, Ctrl+C `slam.sh`.

Remember where the robot started and which way it faced: that spot is
`0 0 0` on the map. Mark it on the floor with tape.

Expected:

```
  [OK]   /map published
  [OK]   saved .../robot/maps/room429.{pgm,yaml}
         size       160 x 120 cells = 8.0 x 6.0 m (resolution 0.050 m)
         free        42.0 %  (20.2 m^2)
  [OK]   map has enough free space
```

If it fails: no `/map` means SLAM is not running or gets no `/scan`
(stage 1). A bent or doubled map means you turned too fast; map again.

Copy back and keep in git (from the laptop):

```bash
scp <user>@<jetson-ip>:~/object-finder-bot/robot/maps/room429.* robot/maps/
git add robot/maps/room429.* && git commit -m "Add the classroom map" && git push
```

Any image viewer opens the `.pgm` (white free, black walls, gray unknown).

## Stage 3: localization and one Nav2 goal

Place the robot on the tape mark facing the mapping direction. Stop
`slam.sh` (SLAM and AMCL must not run together). Keep `bringup.sh` running.

```bash
./robot/nav.sh room429                # pane 2: wait for "Managed nodes are active"
./robot/set_initial_pose.sh 0 0 0     # pane 3
./robot/check_stage3.sh               # pane 3: drives 0.5 m ahead, then back
```

Other goals: `./robot/goto.sh 1.0 0.5 1.57` (x, y in meters, yaw in radians,
map frame). Ctrl+C cancels a goal.

Expected:

```
  [OK]   node amcl
  [OK]   amcl is active
  [OK]   map -> base_link: 0.012 -0.004 0.010 (x y yaw)
  [OK]   AMCL covariance xx=0.021 yy=0.018 (converged)
  [OK]   goal reached in 9s
  [OK]   back at the start pose
```

If it fails:

| Symptom | Check |
|---|---|
| `amcl state: inactive` or no `/map` | Map path wrong (`ls robot/maps`), read the nav pane |
| No `map -> base_link` | Run `set_initial_pose.sh` again |
| AMCL not converged | Turn in place a little with `teleop.sh`, set the pose again |
| Goal aborted | Goal inside an obstacle or unknown space, path blocked, robot not where AMCL thinks |
| Robot too fast or wobbly | `OFB_MAX_VEL=0.1 ./robot/nav.sh room429` |

Copy back: `scp -r <user>@<jetson-ip>:~/object-finder-bot/robot/logs ./`

## Stage 4: camera and vision worker (both camera versions)

No ROS needed. Mount the camera on the mast (see "Camera mount" below).

Depth version (Intel RealSense, on a blue USB 3 port):

```bash
./robot/check_stage4.sh depth
```

No-depth version (Logitech C920):

```bash
./robot/check_stage4.sh nodepth
```

With both cameras plugged in: `./robot/check_stage4.sh both`. To test only the
HTTP path without the GPU: `./robot/check_stage4.sh depth --fake`. To try YOLO:
`OFB_DETECTOR=yolo ./robot/check_stage4.sh depth`.

The check starts the worker itself (first start: CLIP loads and detectNet may
build a TensorRT engine, 1-5 minutes), calls `/health`, five `/detect_embed`
calls with timing, `/embed_text`, and `/verify`, and stops the worker. Point
the camera at a desk with a few objects.

Expected (depth):

```
  [OK]   RealSense: Intel Corp. ...
  [OK]   import torch 2.1.0
  [OK]   CUDA available: Xavier
  [OK]   import pyrealsense2
  [OK]   worker has a camera
  [OK]   camera_mode is depth
  [OK]   /detect_embed x5: mean 180 ms, max 260 ms, detections per frame [3, 4, 3, 3, 4]
  [OK]   depth_m filled for 12 detection(s)
  [OK]   /verify 'a cup': found=True prob=0.64 ...
```

In nodepth mode, `depth_m is null in nodepth mode` must be `[OK]`.

If it fails:

| Symptom | Check |
|---|---|
| `import pyrealsense2` fails | librealsense Python bindings in the conda env (`vision/README.md`) |
| `CUDA available` fails | Wrong conda env or a CPU-only torch; never reinstall torch, pick the right env (`OFB_CONDA_ENV`) |
| Worker has no camera | Camera unplugged or busy (another program has it: `vision/find_object.py`, an old worker) |
| No `depth_m` in depth mode | Objects closer than `depth_min` (0.3 m) or farther than `depth_max` (4 m) |
| `/detect_embed` over 3 s | Use FP16, detectNet, close other GPU programs (`tegrastats` shows memory) |
| Only 1.5 GB free | Stop other programs; CLIP + detector need about 2 GB |

The worker log is `robot/logs/<timestamp>/worker.log`. Copy back:
`scp -r <user>@<jetson-ip>:~/object-finder-bot/robot/logs ./`

## Stage 5: the full loop

Robot on the tape mark, camera mounted, `robot/config/<mode>.yaml` written
(see "Camera mount"). Stop any `bringup.sh`, `nav.sh`, or worker you started
by hand (Ctrl+C), then:

```bash
./robot/start_all.sh room429 depth      # or: nodepth
tmux attach -t ofb
```

The `ofb` session has one pane each for bringup, nav, the vision worker,
the objmem nodes, and `ask` (plus `camera` if `OFB_IMAGE_SOURCE=ros`). The
objmem pane waits for Nav2, sets the initial pose (`OFB_INIT_POSE`, default
`0 0 0`), waits for the worker, then launches
`ros2 launch objmem_ros objmem.launch.py`.

Let the robot see the objects: drive it around with `./robot/teleop.sh` in a
new pane (`Ctrl+B c` opens a new window), stopping for a second at each desk
(the observer records only while the robot stands still). Watch the map in the
laptop browser: `http://<jetson-ip>:8555/`.

Then ask, in the `ask` pane:

```
q where is the blue mug
```

or run the check from another window:

```bash
./robot/check_stage5.sh "a blue mug"
```

Expected:

```
  [OK]   vision worker: {"ok": true, "camera": true, "camera_mode": "depth"}
  [OK]   node /objmem_observer
  [OK]   node /objmem_finder
  [OK]   node /objmem_mapview
  [OK]   map view http://<jetson-ip>:8555/ answers
  [OK]   published /query
  [..]   status: query: a blue mug
  [..]   status: candidates: id=3 sim=0.31 p=0.82 score=0.79
  [..]   status: goal_sent: #1 x=1.20 y=0.40 yaw=1.57
  [..]   status: goal_reached: #1
  [..]   status: recheck: found prob=0.71
  [OK]   result: found id=3 x=1.25 y=1.00 p=0.95
```

Stop everything (the memory is saved on shutdown):

```bash
./robot/stop_all.sh
```

The memory persists in `robot/memory/<map>_<mode>.npz` and is loaded at the
next start; delete it to start empty. Each query is logged to
`robot/memory/search_<map>_<mode>.jsonl` for `scripts/evaluate.py`.

Run stage 5 once with `depth` and once with `nodepth`.

If it fails:

| Symptom | Check |
|---|---|
| A pane shows `[FAIL]` | Read its hint; fix; press Up and Enter in that pane to rerun |
| No objmem nodes | `./robot/build_ws.sh` (after `git pull`), read the objmem pane |
| `candidates:` empty / `result: empty` | The memory is empty: let the robot look at the desks while stopped |
| Robot drives to the wrong place | Camera mount values (`cam_*`), or AMCL lost (check_stage3.sh) |
| Re-check never finds the object | `found_thresh` too high; `scripts/tune_verify.py` |

Copy back (logs with all pane output, the memory, the search log):

```bash
scp -r <user>@<jetson-ip>:~/object-finder-bot/robot/logs ./
scp -r <user>@<jetson-ip>:~/object-finder-bot/robot/memory ./
```

## Camera mount: measure and write it down

The memory places objects with the camera pose in `base_link`. Measure after
the mast is fixed, and again whenever the camera is moved. `base_link` on the
Waffle Pi is the midpoint between the two drive wheel centers, about 1 cm
above the floor; x points forward, y to the left, z up.

| Key | How to measure | Unit |
|---|---|---|
| `cam_x` | Floor distance from the wheel axle (line between the wheel centers) forward to the lens. Behind the axle is negative. | m |
| `cam_y` | Sideways from the robot center line to the lens, left positive | m |
| `cam_z` | Height of the lens above the floor, minus 0.01 | m |
| `cam_yaw` | Camera turned left of straight ahead is positive (usually 0) | rad |
| `cam_pitch` | Tilt down is positive. With a phone level app on the camera top, or `atan(drop / length)` measured along the camera body | rad |

Degrees to radians: multiply by 0.01745 (10 deg = 0.175 rad).

Write the values in a per-camera config, which the scripts use instead of
`config/default.yaml` (do not edit `config/default.yaml` in the classroom;
`git pull` would conflict):

```bash
cp config/default.yaml robot/config/depth.yaml      # RealSense
cp config/default.yaml robot/config/nodepth.yaml    # C920
nano robot/config/depth.yaml                        # cam_x ... cam_pitch, fx fy cx cy, hfov
```

Intrinsics:

- RealSense: `conda activate test1001 && python vision/print_intrinsics.py`
  prints `img_w img_h fx fy cx cy hfov` for 640x480; paste them into
  `robot/config/depth.yaml`.
- C920: `python vision/print_intrinsics.py --width 640 --height 480 --c920-hfov-deg 70`
  gives an estimate. To measure the field of view: stand the robot `D` meters
  from a wall, find the visible width `W` on the wall, then
  `hfov = 2 * atan(W / (2 * D))` and `fx = fy = (img_w / 2) / tan(hfov / 2)`.

Quick check of the mount: put a cup on a desk 1.0 m straight ahead of the robot,
run stage 5, and look at the map view: the cup should appear
about 1.0 m in front of the robot. If it is shifted sideways, fix `cam_yaw` or
`cam_y`; if it is too near or far, fix `cam_pitch` (depth) or the intrinsics.

Copy the configs back and commit them from the laptop:

```bash
scp <user>@<jetson-ip>:~/object-finder-bot/robot/config/*.yaml robot/config/
```

## OpenCR firmware

If `bringup.sh` stays at `Failed connection with Devices`, the OpenCR board
runs firmware for another ROS version. Flash the ROS 2 firmware (OpenCR USB
to the Jetson, robot power ON):

```bash
sudo dpkg --add-architecture armhf && sudo apt update && sudo apt install -y libc6:armhf
cd /tmp && wget https://github.com/ROBOTIS-GIT/OpenCR-Binaries/raw/master/turtlebot3/ROS2/latest/opencr_update.tar.bz2
tar -xzf opencr_update.tar.bz2 && cd opencr_update   # gzip despite the .bz2 name (-xjf fails)
./update.sh /dev/ttyACM0 waffle.opencr     # Waffle Pi uses the "waffle" firmware
```

Wait for `jump_to_fw`, then rerun `./robot/bringup.sh`.

## Demo helpers (added 2026-11-19)

| Script | What it does |
|---|---|
| `install_realsense_jetson.sh` | Builds librealsense (RSUSB backend) with Python bindings for the conda env, so `import pyrealsense2` works for depth mode. 30-90 min, run in tmux. Adapted from JetsonHacks installRealSenseSDK. |
| `patrol.sh` | Drives through saved waypoints and stops at each so the observer records the desks. `--add` saves the current pose; replaces teleop patrolling in stage 5 and the demo. |
| `voice.sh` | Spoken queries: microphone (USB or the C920's) -> Whisper in the conda env -> `/query`. `--dry-run` only prints the text; `--trt` uses NVIDIA-AI-IOT/whisper_trt. |

Patrol in the demo (nav.sh / start_all.sh running, initial pose set):

```bash
./robot/teleop.sh                 # drive to a spot facing a desk, then in another window:
./robot/patrol.sh --add room429   # repeat for each desk
./robot/patrol.sh room429 1 3     # 1 round, 3 s per stop
```

## What to bring back after class

| What | Where on the Jetson |
|---|---|
| All script output | `robot/logs/` |
| Maps | `robot/maps/*.pgm`, `*.yaml` (commit) |
| Camera configs | `robot/config/*.yaml` (commit) |
| Memory files and search logs | `robot/memory/` |
| Rosbags | `robot/bags/` (large; do not commit) |

```bash
scp -r <user>@<jetson-ip>:~/object-finder-bot/robot/{logs,maps,config,memory} ./from_jetson/
```
