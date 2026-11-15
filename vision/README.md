# vision/: Jetson vision tools

Stand-alone tools for the camera, the detector, and CLIP on the Jetson. They
use the `objmem` package (`src/objmem/`): `camera.py` and `detectors.py` for the
hardware, `embed.py`, `crops.py`, and `verify.py` for CLIP. The robot itself uses
the vision worker (`scripts/vision_worker.py`), not these scripts; run these to
check the camera and to measure speed before the full loop.

| Script | What it does |
|---|---|
| `find_object.py` | Camera-only demo: live video with detector boxes in the browser; remember objects, search memory or the current frame by text |
| `bench_clip.py` | CLIP latency (1, 9, 83 crops; text) and GPU memory, FP32 vs FP16 |
| `bench_detector.py` | detectNet vs YOLO on the same frames: FPS, boxes per frame, memory |
| `print_intrinsics.py` | RealSense color intrinsics printed as `config/default.yaml` keys |

## Setup (once per SSH session)

```bash
ssh <user>@<JETSON-IP>
tmux new -s vision            # or: tmux attach -t vision
conda activate test1001
cd ~/object-finder-bot        # the repo
export PYTHONPATH=$PWD/src
```

Do not reinstall `torch`; the conda env already has the Jetson CUDA build.
Extra Python packages, only if missing:

```bash
pip install open_clip_torch                 # CLIP (find_object, bench_clip)
pip install ultralytics --no-deps           # YOLO only; --no-deps keeps the Jetson torch
pip install pyrealsense2                    # RealSense, if `python -c "import pyrealsense2"` fails
```

`jetson_inference` and `jetson_utils` come from the jetson-inference build
(detectNet, the C920 reader, and the WebRTC video output). Without
`jetson_utils` the C920 is read with OpenCV and `--output none` must be used.

Find the cameras: `ls /dev/video*` (the C920 is usually `/dev/video0`; a
RealSense adds several `/dev/video*` nodes) and `rs-enumerate-devices` for the
RealSense.

## find_object.py

```bash
python vision/find_object.py                                    # C920 1920x1080, detectNet
python vision/find_object.py --input /dev/video2                # another device
python vision/find_object.py --camera realsense                 # RealSense color 640x480
python vision/find_object.py --detector yolo --yolo-engine ~/models/yolov8n.engine
python vision/find_object.py --config config/default.yaml       # found_thresh, crop_pad, prompts
python vision/find_object.py --output none                      # no video, terminal only
```

Open `http://<JETSON-IP>:8554` in the laptop browser for the video. Loading
CLIP takes about 15 s; the first detectNet run builds a TensorRT engine
(several minutes, cached afterwards).

Commands (type and press Enter):

| Command | Effect |
|---|---|
| `s` | remember the objects detected in the current frame |
| `t` | remember the current frame as 3x3 tiles (objects the detector does not know) |
| `q <text>` | search the memories (`q a red mug`); the best box is shown for 5 s; `vision/memory/result.jpg` |
| `f <text>` | search the current frame: detections + 83 sliding windows, the same re-check the robot does on arrival; `vision/memory/result_now.jpg` |
| `l` | list memories |
| `x` | clear all memories |
| `h` | help |
| `exit` | quit (or Ctrl+C) |

Memories are kept in `vision/memory/memory.npz` (crops in `vision/memory/crops/`)
and reload on the next start. Copy result images to the laptop with
`scp <user>@<JETSON-IP>:~/object-finder-bot/vision/memory/result_now.jpg .`

`f` prints `-> found` when the best window probability is at least
`found_thresh` (0.5). Use it to tune `found_thresh` and `background_prompts`
before the full loop.

On a PC, without any hardware: `python vision/find_object.py --fake --output none`
(fake camera, fake detector, fake CLIP).

## bench_clip.py

```bash
python vision/bench_clip.py                       # FP32 then FP16, synthetic crops
python vision/bench_clip.py --precision fp16 --images ~/jetson-inference/build/aarch64/bin/images
```

Prints a Markdown table: load time, ms for 1, 9, and 83 crops, ms per crop,
ms per sentence, GPU memory after loading and at peak. 83 crops is one re-check
of a 16:9 frame. Watch the total memory with `tegrastats` or `jtop` in another
tmux pane; CPU and GPU share 8 GB.

## bench_detector.py

```bash
python vision/bench_detector.py                                  # C920 1280x720, detectNet and YOLO
python vision/bench_detector.py --camera realsense --frames 200
python vision/bench_detector.py --detectors yolo --yolo-engine ~/models/yolov8n.engine
python vision/bench_detector.py --images ~/test_photos           # the 10 test objects, photographed
```

Frames are captured first, and every detector runs on the same frames. The
table shows ms per frame, FPS, boxes per frame, the share of frames with at
least one box, mean confidence, load time, and the memory added; the label
counts are printed above it. Put an object set on the desk in view while it runs.

YOLO TensorRT engine (once, several minutes; the `.pt` file downloads on first use):

```bash
yolo export model=yolov8n.pt format=engine half=True imgsz=640
```

A detector that fails to load prints `[FAIL] <name>: <error>` and the others still run.

## print_intrinsics.py

```bash
python vision/print_intrinsics.py                          # RealSense color 640x480
python vision/print_intrinsics.py --width 1280 --height 720
python vision/print_intrinsics.py --width 640 --height 480 --c920-hfov-deg 70   # C920 estimate
```

Example output:

```
# RealSense color 640x480 (depth aligned to color), depth scale 0.001 m/unit
img_w: 640
img_h: 480
fx: 615.12
fy: 615.40
cx: 322.07
cy: 238.51
hfov: 0.9578          # rad (54.9 deg)
# depth check: 87% valid pixels, median 1.42 m
```

Copy these lines into the config file the robot uses (for example a copy of
`config/default.yaml`), replacing the existing keys. Use the same resolution
the vision worker uses.

## Python API used here

```python
from objmem.camera import make_camera, camera_for_mode
cam = make_camera("realsense", width=640, height=480)    # Frame(color RGB, depth meters, t)
cam = make_camera("c920", device="/dev/video0", width=1280, height=720, backend="auto")
cam = make_camera(camera_for_mode("nodepth"))            # "depth" -> realsense, "nodepth" -> c920
frame = cam.read()                                       # None when no frame arrived

from objmem.detectors import make_detector
det = make_detector("detectnet", network="ssd-mobilenet-v2", threshold=0.5)
det = make_detector("yolo", model="yolov8n.pt", engine=None, conf=0.4)
boxes = det.detect(frame.color)                          # [RawBox(box=(l, t, r, b), label, conf)]
```

`make_camera("fake")`, `make_detector("fake")`, and `make_camera("none")` (returns
None) are for PCs and tests.
