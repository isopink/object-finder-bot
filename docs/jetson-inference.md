# jetson-inference Notes

[jetson-inference](https://github.com/dusty-nv/jetson-inference) is NVIDIA's deep-learning inference library for Jetson, published as the "Hello AI World" tutorial. It runs pretrained vision models on the Jetson GPU in real time through TensorRT, with C++ and Python APIs.

The first run of a model builds a TensorRT engine for that GPU, which takes a while. Later runs load the cached engine and start immediately.

## Features

| Class | Task | Bundled models | Output |
|-------|------|----------------|--------|
| `imageNet` | Image classification | ResNet-18/50/101/152, GoogleNet, VGG, Inception-v4 | Class and confidence for the whole image |
| `detectNet` | Object detection | SSD-Mobilenet-v2 (COCO, 91 classes), PeopleNet, FaceDetect, DashCamNet | Bounding box, class, and confidence per object |
| `segNet` | Semantic segmentation | FCN-ResNet18 (Cityscapes, Pascal VOC, SUN RGB-D) | Class per pixel |
| `poseNet` | Pose estimation | ResNet18, DenseNet121 | 18 body or 21 hand keypoints |
| `actionNet` | Action recognition | ResNet18/34 (Kinetics) | Action class over consecutive frames |
| `backgroundNet` | Background removal | | Foreground person or object only |
| `depthNet` | Monocular depth | | Relative depth per pixel from one camera |

The companion library **jetson-utils** handles video I/O (V4L2 USB cameras, CSI cameras, video files, RTSP, WebRTC, display) and CUDA image operations (crop, resize, text overlay) without extra GPU memory copies.

Models fine-tuned in PyTorch on custom data can be exported to ONNX and run the same way.

## Lab observations

Setup: Jetson Xavier NX (ASUS PE1000N), Logitech C920, jetson-inference built in a Conda environment.

- **Install check**: the `imageNet` example ran correctly.
- **Detection**: C920 video was streamed to a laptop browser over WebRTC with `detectNet` (SSD-Mobilenet-v2) overlays.
  - About 30 FPS under normal lighting.
  - Detected laptop, person, cup, and clock, among others.
  - Detection was unreliable in dim light and for occluded or cropped objects.
- **Segmentation**: `segNet` (FCN-ResNet18) ran on the same setup.

## How this project uses it

- `detectNet` proposes object boxes. Each box is cropped and embedded with CLIP ([`objmem.crops`](../src/objmem/crops.py), [`vision/find_object.py`](../vision/find_object.py)).
- `videoSource` / `videoOutput` provide the camera input and the WebRTC view in the browser.
- SSD-Mobilenet-v2 only knows the COCO classes, and it misses objects in poor conditions. This is why the project adds CLIP for free-text search, tiles and sliding windows for objects the detector does not know, and a CLIP re-check on arrival ([proposal](proposal.md), section 4.4).
