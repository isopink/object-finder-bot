# Shared environment, sourced by the other scripts.
# The robot and the Jetson/laptop must use the same values to see each other's topics.
export ROS_DISTRO="${ROS_DISTRO:-humble}"
export TURTLEBOT3_MODEL="${TURTLEBOT3_MODEL:-waffle_pi}"
export ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-30}"   # unique per team, to avoid mixing with other robots
export LDS_MODEL="${LDS_MODEL:-LDS-02}"       # LiDAR model (LDS-01 / LDS-02, see the sticker on the robot)

source "/opt/ros/${ROS_DISTRO}/setup.bash"
SLAM_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export SLAM_DIR
