# ROS 2 Humble for the Jetson (arm64), used when the Waffle Pi runs Humble.
# The ROS side only: bringup, SLAM, AMCL, Nav2, objmem_ros. No GPU, no PyTorch:
# the vision worker keeps running in the conda env on the host (port 8600).
#
# Build and run with robot/docker/run.sh (it passes the right flags):
#   ./robot/docker/run.sh build
#   ./robot/docker/run.sh            # shell inside the container
FROM ros:humble-ros-base

ENV DEBIAN_FRONTEND=noninteractive \
    TURTLEBOT3_MODEL=waffle_pi \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
      ros-humble-turtlebot3 ros-humble-turtlebot3-msgs ros-humble-turtlebot3-bringup \
      ros-humble-turtlebot3-teleop ros-humble-turtlebot3-navigation2 \
      ros-humble-dynamixel-sdk ros-humble-hls-lfcd-lds-driver \
      ros-humble-slam-toolbox \
      ros-humble-navigation2 ros-humble-nav2-bringup ros-humble-nav2-msgs ros-humble-nav2-map-server \
      ros-humble-rosbag2 ros-humble-rosbag2-storage-default-plugins ros-humble-rosbag2-storage-mcap \
      ros-humble-tf2-ros ros-humble-tf2-tools ros-humble-visualization-msgs \
      ros-humble-image-transport-plugins ros-humble-cv-bridge \
      python3-colcon-common-extensions python3-numpy python3-yaml python3-pip \
      libudev-dev build-essential git curl tmux usbutils v4l-utils \
    && rm -rf /var/lib/apt/lists/*

# Camera ROS nodes, only for image_source:=ros. Optional: skipped if apt has no arm64 build.
RUN apt-get update && (apt-get install -y --no-install-recommends ros-humble-realsense2-camera ros-humble-v4l2-camera \
      || echo "camera ROS packages not installed") && rm -rf /var/lib/apt/lists/*

# LDS-02 LiDAR driver: from apt when released, otherwise from source.
RUN if apt-get update && apt-get install -y --no-install-recommends ros-humble-ld08-driver; then \
      echo "ld08_driver from apt"; \
    else \
      mkdir -p /opt/tb3_ws/src && cd /opt/tb3_ws/src && \
      (git clone -b ros2-devel https://github.com/ROBOTIS-GIT/ld08_driver.git \
        || git clone https://github.com/ROBOTIS-GIT/ld08_driver.git) && \
      cd /opt/tb3_ws && . /opt/ros/humble/setup.sh && \
      colcon build --symlink-install --parallel-workers 2; \
    fi && rm -rf /var/lib/apt/lists/*

# Every shell in the container gets the same environment as the host scripts.
RUN echo 'if [ -n "$OFB_REPO" ] && [ -f "$OFB_REPO/robot/env.sh" ]; then source "$OFB_REPO/robot/env.sh"; else source /opt/ros/humble/setup.bash; fi' >> /etc/bash.bashrc

WORKDIR /root
CMD ["bash"]
