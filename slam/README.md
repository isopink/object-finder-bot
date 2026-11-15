# SLAM (ROS 2 + TurtleBot3 Waffle Pi)

Stage 0 of the [object-finding robot](../README.md): **build a map with the Waffle Pi's LiDAR**.

- ROS 2 **Humble** (Ubuntu 22.04)
- SLAM: `slam_toolbox` (default) or `cartographer` (the TurtleBot3 reference setup)
- Workflow: develop in Gazebo, push, then pull in the lab and verify on the real robot

> Check the ROS 2 distro on the Waffle Pi first. If it is not Humble, change `ROS_DISTRO` in `scripts/env.sh` and the install script to match. Machines on different distros are not guaranteed to communicate.

## Layout

```
slam/
├── scripts/
│   ├── env.sh                  shared environment (ROS_DOMAIN_ID, robot model, ...)
│   ├── install_ros2_humble.sh  install ROS 2, TurtleBot3, and SLAM packages
│   ├── sim_slam.sh             SLAM in Gazebo
│   ├── save_map.sh             save the map to maps/
│   ├── robot_bringup.sh        [Waffle Pi] start sensors and motors
│   ├── verify_stage0.sh        [lab] verify SLAM on the real robot, record a rosbag
│   └── replay_bag.sh           re-run SLAM on a recorded rosbag
├── maps/                       saved maps (.pgm, .yaml), tracked in Git
├── bags/                       rosbags, not tracked (large)
└── logs/                       verification logs, not tracked
```

## 1. Setup (Windows with WSL2)

In an **administrator** PowerShell:

```powershell
wsl --install -d Ubuntu-22.04
```

Windows 11 ships WSLg, so Gazebo and RViz windows open directly. Then, in the Ubuntu terminal:

```bash
git clone https://github.com/isopink/uos_ir.git ~/uos_ir
cd ~/uos_ir/slam
./scripts/install_ros2_humble.sh
source ~/.bashrc
```

> Clone inside WSL (`~/uos_ir`). Running from a Windows folder (`/mnt/c/...`) is slow and causes permission problems.

## 2. SLAM in simulation

Terminal 1, Gazebo + SLAM + RViz:

```bash
./scripts/sim_slam.sh slam_toolbox world     # or: cartographer house
```

Terminal 2, keyboard teleop (`w/x` forward/back, `a/d` turn, `s` stop):

```bash
ros2 run turtlebot3_teleop teleop_keyboard
```

Terminal 3, once the map is complete:

```bash
./scripts/save_map.sh sim_world_toolbox
```

Drive slowly, keep in-place rotations short, and return to the start once to close the loop.

## 3. SLAM on the real Waffle Pi

`ROS_DOMAIN_ID` in `scripts/env.sh` must be the same on every machine, and different from other teams' robots.

On the Waffle Pi (over SSH):

```bash
cd ~/uos_ir/slam && git pull
./scripts/robot_bringup.sh
```

On the Jetson or a lab PC:

```bash
cd ~/uos_ir/slam && git pull
./scripts/verify_stage0.sh slam_toolbox    # check topics, then run SLAM
ros2 run turtlebot3_teleop teleop_keyboard # another terminal
./scripts/save_map.sh lab_429              # another terminal, after driving
```

To record data for offline use, record without SLAM:

```bash
./scripts/verify_stage0.sh record
```

> Recording while SLAM runs puts `map → odom` into the bag's `/tf`, which conflicts with SLAM on replay.

## 4. Replay a recorded bag

```bash
./scripts/replay_bag.sh bags/stage0_20261015_140000 cartographer
```

This allows comparing `slam_toolbox` and `cartographer` on the same data, or tuning parameters, without the robot.

## Troubleshooting

| Symptom | Check |
|---------|-------|
| `verify_stage0.sh` reports `/scan` FAIL | Robot bringup is running, same Wi-Fi, same `ROS_DOMAIN_ID` |
| `ros2 topic list` shows nothing | The Wi-Fi may block multicast; consider a Fast DDS Discovery Server |
| Map bends or overlaps | Rotation was too fast, or odometry jumps (`ros2 topic echo /odom`) |
| No LiDAR data | `LDS_MODEL` in `env.sh` matches the robot's LiDAR (LDS-01/02) |
| Gazebo does not open or is very slow | Update WSL (`wsl --update`) and the GPU driver |

## Course topics covered

| Topic | Where it shows up |
|-------|-------------------|
| Motion models | `/odom`: wheel odometry and its accumulated drift |
| Sensor models | `/scan`: LiDAR beam model |
| Occupancy grid maps | The saved `.pgm` (white free, black occupied, gray unknown) |
| Particle filter | Nav2 AMCL localization on the saved map |
| Graph-based SLAM | `slam_toolbox` (pose graph, loop closure), `cartographer` |
