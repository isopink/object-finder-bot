#!/usr/bin/env bash
# Install ROS 2 Foxy natively on the Jetson (Ubuntu 20.04) with everything the
# robot needs: TurtleBot3, slam_toolbox, Nav2, rosbag2, tmux, udev rules for the
# OpenCR board and the LiDAR. Safe to run again: finished steps are skipped.
#
# Usage: ./robot/install_foxy_jetson.sh [--with-cameras]
#   --with-cameras  also install realsense2_camera and v4l2_camera (only needed
#                   for image_source:=ros; the default reads the camera in the
#                   vision worker)
#
# Never touches conda, PyTorch, or CUDA. Takes 10-30 minutes on the Jetson.
set -uo pipefail
source "$(dirname "$0")/env.sh"
ofb_log_init install_foxy

WITH_CAMERAS=0
[ "${1:-}" = "--with-cameras" ] && WITH_CAMERAS=1

if [ -n "${CONDA_PREFIX:-}" ]; then
  echo "[FAIL] a conda env is active ($CONDA_DEFAULT_ENV)."
  echo "       hint: run 'conda deactivate' (until no env is active), then run this again"
  exit 1
fi

echo "== 1. System"
CODENAME="$(lsb_release -cs 2>/dev/null || echo unknown)"
if [ "$CODENAME" = focal ]; then ok "Ubuntu 20.04 (focal)"; else
  fail "Ubuntu is $CODENAME, Foxy needs focal" "on Ubuntu 22.04 use Humble: ./robot/docker/run.sh build"
  ofb_summary; exit 1
fi
info "arch $(uname -m), JetPack: $(dpkg-query -W -f='${Version}' nvidia-jetpack 2>/dev/null || echo unknown)"

echo "== 2. ROS 2 apt repository"
sudo apt-get update
sudo apt-get install -y software-properties-common curl gnupg lsb-release locales
sudo locale-gen en_US en_US.UTF-8 >/dev/null
sudo add-apt-repository -y universe >/dev/null
if [ ! -f /usr/share/keyrings/ros-archive-keyring.gpg ]; then
  sudo curl -sSL https://raw.githubusercontent.com/ros/rosdistro/master/ros.key \
    -o /usr/share/keyrings/ros-archive-keyring.gpg
fi
REPO_URL="http://packages.ros.org/ros2/ubuntu"
# Foxy is end-of-life. If its packages ever leave the main repository,
# rerun with OFB_FOXY_SNAPSHOT=1 to use the frozen final snapshot instead.
if [ "${OFB_FOXY_SNAPSHOT:-0}" = 1 ]; then REPO_URL="http://snapshots.ros.org/foxy/final/ubuntu"; fi
echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/ros-archive-keyring.gpg] $REPO_URL focal main" \
  | sudo tee /etc/apt/sources.list.d/ros2.list >/dev/null
sudo apt-get update
if apt-cache policy ros-foxy-ros-base | grep -q 'Candidate: [0-9]'; then
  ok "ros-foxy packages available from $REPO_URL"
else
  fail "ros-foxy-ros-base not found in $REPO_URL" "rerun with OFB_FOXY_SNAPSHOT=1 ./robot/install_foxy_jetson.sh"
  ofb_summary; exit 1
fi

echo "== 3. ROS packages"
PKGS=(
  ros-foxy-ros-base
  ros-foxy-turtlebot3 ros-foxy-turtlebot3-msgs ros-foxy-turtlebot3-bringup
  ros-foxy-turtlebot3-teleop ros-foxy-turtlebot3-navigation2
  ros-foxy-dynamixel-sdk ros-foxy-hls-lfcd-lds-driver
  ros-foxy-slam-toolbox
  ros-foxy-navigation2 ros-foxy-nav2-bringup ros-foxy-nav2-msgs ros-foxy-nav2-map-server
  ros-foxy-rosbag2 ros-foxy-rosbag2-storage-default-plugins
  ros-foxy-tf2-ros ros-foxy-tf2-tools ros-foxy-visualization-msgs
  ros-foxy-image-transport-plugins ros-foxy-cv-bridge
  python3-colcon-common-extensions python3-rosdep python3-argcomplete
  python3-numpy python3-yaml python3-pip
  libudev-dev build-essential git tmux curl
)
sudo apt-get install -y "${PKGS[@]}"
if dpkg -s ros-foxy-turtlebot3-bringup ros-foxy-slam-toolbox ros-foxy-nav2-bringup >/dev/null 2>&1; then
  ok "TurtleBot3, slam_toolbox, Nav2 installed"
else
  fail "some ROS packages did not install" "read $OFB_LOG_FILE for the apt error"
fi
# Optional: MCAP storage for rosbag2 (record.sh uses sqlite3 unless OFB_BAG_STORAGE=mcap).
sudo apt-get install -y ros-foxy-rosbag2-storage-mcap >/dev/null 2>&1 \
  && ok "rosbag2 MCAP storage" || info "rosbag2 MCAP storage not available (sqlite3 is used)"
if [ "$WITH_CAMERAS" = 1 ]; then
  sudo apt-get install -y ros-foxy-realsense2-camera ros-foxy-v4l2-camera \
    && ok "realsense2_camera, v4l2_camera" || fail "camera ROS packages" "only needed for image_source:=ros"
fi

echo "== 4. LDS-02 LiDAR driver (ld08_driver)"
# shellcheck disable=SC1091
set +u; source /opt/ros/foxy/setup.bash; set -u
if ros2 pkg prefix ld08_driver >/dev/null 2>&1; then
  ok "ld08_driver already available"
elif sudo apt-get install -y ros-foxy-ld08-driver >/dev/null 2>&1; then
  ok "ld08_driver from apt"
else
  WS="${OFB_TB3_WS:-$HOME/turtlebot3_ws}"
  mkdir -p "$WS/src"
  [ -d "$WS/src/ld08_driver" ] || git clone -b ros2-devel https://github.com/ROBOTIS-GIT/ld08_driver.git "$WS/src/ld08_driver" \
    || git clone https://github.com/ROBOTIS-GIT/ld08_driver.git "$WS/src/ld08_driver"
  if (cd "$WS" && colcon build --symlink-install --parallel-workers 2); then
    ok "ld08_driver built in $WS"
  else
    fail "ld08_driver build failed" "only needed for LDS_MODEL=LDS-02; read $OFB_LOG_FILE"
  fi
fi

echo "== 5. udev rules and permissions"
sudo cp "$OFB_ROBOT_DIR/udev/99-ofb-robot.rules" /etc/udev/rules.d/
sudo udevadm control --reload-rules && sudo udevadm trigger
ok "udev rules installed (/dev/opencr, /dev/lidar symlinks, mode 0666)"
# ModemManager grabs /dev/ttyACM* (the OpenCR) for a few seconds after plug-in.
if systemctl list-unit-files 2>/dev/null | grep -q '^ModemManager'; then
  sudo systemctl disable --now ModemManager >/dev/null 2>&1 && ok "ModemManager disabled"
fi
for g in dialout video plugdev; do
  if getent group "$g" >/dev/null && ! id -nG "$USER" | grep -qw "$g"; then
    sudo usermod -aG "$g" "$USER" && info "added $USER to $g (log out and back in once)"
  fi
done

echo "== 6. Shell setup"
LINE="source $OFB_ROBOT_DIR/env.sh"
if grep -qxF "$LINE" ~/.bashrc; then ok "$HOME/.bashrc already sources robot/env.sh"; else
  echo "$LINE" >> ~/.bashrc && ok "added to ~/.bashrc: $LINE"
fi

echo "== 7. Build objmem_ros"
if "$OFB_ROBOT_DIR/build_ws.sh"; then ok "objmem_ros built"; else
  fail "objmem_ros build failed" "run ./robot/build_ws.sh and read its output"
fi

ofb_summary
echo "Next: open a new SSH session (or 'source ~/.bashrc'), then ./robot/check_stage1.sh"
