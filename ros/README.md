# objmem_ros: ROS 2 nodes

An `ament_python` package that builds unchanged on **Foxy** (native, Ubuntu
20.04 on the Jetson) and **Humble** (the Docker image in `robot/docker/`).

| Executable | What it does |
|---|---|
| `objmem` | observer + finder + mapview in one process, sharing one memory (the launch file starts this) |
| `observer` | pose from TF `map -> base_link`, 1 to 2 Hz, only while the robot stands still; asks the vision worker for detections, places them on the map, updates the memory, saves it every `save_period_s` and on shutdown |
| `finder` | subscribes `/query`, runs `objmem.search.find` with a Nav2 `navigate_to_pose` navigator and the worker re-check; progress on `/objmem/status` |
| `mapview` | `http://<jetson-ip>:8555/` page (auto-refresh), `/map.png`, `/items.json`; publishes `/objmem/markers` |
| `ask` | terminal: `q <text>` publishes `/query` and prints `/objmem/status`; `--voice` adds `v` (Whisper) |
| `fake_nav2` | fake `navigate_to_pose` server for tests and dry runs without Nav2 |

## Build

The `objmem` Python package must be importable by the ROS Python (system
`python3`, not conda). Use `PYTHONPATH`; do not reinstall torch.

Foxy on the Jetson:

```bash
source /opt/ros/foxy/setup.bash
export PYTHONPATH=~/object-finder-bot/src:$PYTHONPATH   # robot/env.sh does this
sudo apt install ros-foxy-nav2-msgs python3-numpy python3-yaml
cd ~/object-finder-bot/ros
colcon build --packages-select objmem_ros
source install/setup.bash
```

Humble in Docker (inside `robot/docker/run.sh`, repo mounted): the same
commands with `humble` in place of `foxy`.

`ros/build`, `ros/install`, `ros/log` are build output (ignored by git).
After `git pull`, run `colcon build` again.

## Run

Start the vision worker first (conda env, outside ROS):

```bash
python scripts/vision_worker.py --config config/default.yaml --port 8600
```

Then, with Nav2 running on a saved map:

```bash
ros2 launch objmem_ros objmem.launch.py \
    config:=$HOME/object-finder-bot/config/default.yaml \
    memory_file:=$HOME/objmem_memory.npz \
    image_source:=worker
```

In another tmux pane:

```bash
ros2 run objmem_ros ask            # or: ask --voice
> q where is the blue mug
  [status] query: where is the blue mug
  [status] candidates: id=3 sim=0.31 p=0.82 score=0.79; ...
  [status] goal_sent: #1 x=1.20 y=0.40 yaw=1.57
  [status] goal_reached: #1
  [status] recheck: found prob=0.71
  [status] result: found id=3 x=1.25 y=1.00 p=0.95
```

Map in the laptop browser: `http://<jetson-ip>:8555/`.

### Launch arguments

| Argument | Default | Meaning |
|---|---|---|
| `config` | (defaults) | objmem YAML (`config/default.yaml`) |
| `memory_file` | `objmem_memory.npz` | loaded at start, saved every 30 s and on Ctrl-C (relative to the launch directory) |
| `image_source` | `worker` | `worker`: the worker reads its own camera; `ros`: subscribe to camera topics and send JPEGs |
| `worker_url` | `http://127.0.0.1:8600` | vision worker |
| `map_yaml` | | `map_saver` `.yaml`, passed to `viz.draw_map` as the occupancy grid |
| `search_log` | | JSON-lines search log for `scripts/evaluate.py` |
| `observe_rate` | `1.0` | observer steps per second |
| `only_when_stopped` | `true` | observe only after the robot stood still for 0.5 s |
| `color_topic` | `/camera/color/image_raw/compressed` | `image_source:=ros` |
| `depth_topic` | `/camera/aligned_depth_to_color/image_raw` | `image_source:=ros`, depth mode (16UC1 mm or 32FC1 m) |
| `camera_info_topic` | `/camera/color/camera_info` | intrinsics override `fx fy cx cy img_w img_h hfov` |

Node parameters not in the launch file (set with `--ros-args -p name:=value`):
`save_period_s` (30), `settle_s` (0.5), `pause_while_navigating` (true),
`worker_timeout` (10), `nav_timeout_s` (120), `nav_action`
(`navigate_to_pose`), `map_frame` (`map`), `base_frame` (`base_link`),
`mapview_port` (from config), `refresh_s` (2).

### Topics

- `/query` (std_msgs/String): query text, from `ask` or `ros2 topic pub --once /query std_msgs/String "data: where is the mug"`.
- `/objmem/status` (std_msgs/String): one line per step: `query:`, `candidates:`,
  `goal_sent:`, `goal_reached:` / `goal_failed:`, `recheck:`, `result:`,
  `observe:`, `busy:`, `error:`.
- `/objmem/cancel` (std_msgs/String): cancel the current goal (`c` in `ask`).
- `/objmem/markers` (visualization_msgs/MarkerArray): covariance ellipses and labels.

### Running the nodes separately (file hand-off)

`ros2 run objmem_ros observer|finder|mapview --ros-args -p memory_file:=<path> -p config:=<yaml>`.
Separate processes share the memory only through the file: the observer
saves it every `save_period_s`; the finder reloads it before a query when it
changed and writes it back after the search; mapview reloads it every second.
Updates made by the finder can be overwritten by the observer's next save, so
use the single-process launch for real runs.

### Dry run without the robot

```bash
python scripts/vision_worker.py --fake &
ros2 run objmem_ros fake_nav2 &
ros2 run tf2_ros static_transform_publisher 0 0 0 0 0 0 map base_link &
ros2 launch objmem_ros objmem.launch.py config:=$PWD/config/default.yaml memory_file:=/tmp/m.npz
ros2 run objmem_ros ask
```

## Tests

- Without ROS (any PC): `python -m pytest ros/objmem_ros/test`
- With ROS (CI, `.github/workflows/ros.yml`, `ros:foxy` and `ros:humble`):
  `colcon build`, the unit tests, `test/ros_e2e.py` (fake worker + fake Nav2
  + finder with a preloaded memory: goal sent, re-check fails, next goal,
  re-check succeeds), and `test/ros_launch_smoke.py` (the launch file,
  mapview HTTP, markers, save on shutdown).
