#!/usr/bin/env bash
# Install ROS 2 Humble, TurtleBot3, and SLAM packages on Ubuntu 22.04 (WSL2 or a lab PC).
set -euo pipefail

if [ "$(lsb_release -cs)" != "jammy" ]; then
  echo "Run this on Ubuntu 22.04 (jammy). Current: $(lsb_release -ds)" >&2
  exit 1
fi

sudo apt update
sudo apt install -y software-properties-common curl locales
sudo locale-gen en_US.UTF-8
sudo add-apt-repository -y universe

sudo curl -sSL https://raw.githubusercontent.com/ros/rosdistro/master/ros.key \
  -o /usr/share/keyrings/ros-archive-keyring.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/ros-archive-keyring.gpg] \
http://packages.ros.org/ros2/ubuntu $(lsb_release -cs) main" \
  | sudo tee /etc/apt/sources.list.d/ros2.list > /dev/null

sudo apt update
sudo apt install -y \
  ros-humble-desktop \
  ros-dev-tools \
  ros-humble-gazebo-ros-pkgs \
  ros-humble-cartographer ros-humble-cartographer-ros \
  ros-humble-slam-toolbox \
  ros-humble-navigation2 ros-humble-nav2-bringup \
  ros-humble-dynamixel-sdk \
  ros-humble-turtlebot3-msgs ros-humble-turtlebot3 \
  ros-humble-turtlebot3-simulations \
  ros-humble-rosbag2-storage-mcap

LINE="source $(cd "$(dirname "$0")" && pwd)/env.sh"
grep -qxF "$LINE" ~/.bashrc || echo "$LINE" >> ~/.bashrc

echo "Done. Open a new terminal or run 'source ~/.bashrc', then run sim_slam.sh."
