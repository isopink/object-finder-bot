Per-camera configs used by the robot scripts instead of config/default.yaml:

- depth.yaml   (RealSense)
- nodepth.yaml (C920)

Create them with `cp config/default.yaml robot/config/<mode>.yaml` and write
the measured camera mount and intrinsics (robot/README.md, "Camera mount").
