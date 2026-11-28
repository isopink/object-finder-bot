"""Start observer + finder + mapview in one process (shared memory).

    ros2 launch objmem_ros objmem.launch.py config:=<yaml> memory_file:=<path> image_source:=worker|ros

Optional: worker_url:=http://127.0.0.1:8600  map_yaml:=<map.yaml>  search_log:=<file.jsonl>
          observe_rate:=1.0  only_when_stopped:=true
          color_topic:=...  depth_topic:=...  camera_info_topic:=...
"""
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node

ARGS = [
    ("config", "", "objmem YAML config (flat Params keys), e.g. <repo>/config/default.yaml"),
    ("memory_file", "objmem_memory.npz", "memory file, loaded at start and saved periodically"),
    ("image_source", "worker", "worker: the vision worker reads the camera; ros: subscribe to camera topics"),
    ("worker_url", "http://127.0.0.1:8600", "vision worker URL"),
    ("map_yaml", "", "map_saver .yaml drawn under the objects in mapview"),
    ("search_log", "", "JSON-lines search log for scripts/evaluate.py"),
    ("evidence_log", "", "JSON-lines log of every look at a remembered place (scripts/fit_detection_range.py)"),
    ("start_mark", "", "map view: 'x y' of the start point, drawn as an X (empty = none)"),
    ("nav_action", "navigate_to_pose", "NavigateToPose action the finder sends goals to (navigate_to_pose_4cmd: gridnav)"),
    ("nav_timeout_s", "120.0", "the finder gives up on one goal after this many seconds"),
    ("observe_rate", "1.0", "observer steps per second asked for (robot/objmem.sh passes 5 while driving)"),
    ("only_when_stopped", "true", "observe only while the robot stands still"),
    ("skip_while_turning", "false", "skip frames while the robot turns (for observing on the move)"),
    ("color_topic", "/camera/color/image_raw/compressed", "image_source:=ros compressed color topic"),
    ("depth_topic", "/camera/aligned_depth_to_color/image_raw", "image_source:=ros aligned depth topic"),
    ("camera_info_topic", "/camera/color/camera_info", "image_source:=ros color camera_info topic"),
]


def generate_launch_description():
    decls = [DeclareLaunchArgument(n, default_value=d, description=h) for n, d, h in ARGS]
    params = {n: LaunchConfiguration(n) for n, _, _ in ARGS}
    # The nodes declare these with dynamic typing and convert strings themselves,
    # so the same file works on Foxy and Humble. No `name=`: the process holds three nodes.
    node = Node(package="objmem_ros", executable="objmem", output="screen",
                emulate_tty=True, parameters=[params])
    return LaunchDescription(decls + [node])
