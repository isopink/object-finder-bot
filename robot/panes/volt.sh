#!/usr/bin/env bash
# Window "battery" of the laptop launcher: battery voltage every 3 s (bringup must be running).
# One small rclpy node that looks at the newest message only: `ros2 topic echo` printed every
# message and used 16 % of a core (2026-11-27).
cd "$(dirname "$0")/../.." || exit 1
export OFB_DDS_WIDE="${OFB_DDS_WIDE:-1}" OFB_ODOM_IMU="${OFB_ODOM_IMU:-0}"
source robot/env.sh >/dev/null 2>&1
set +u
echo "== battery voltage. 11.0-12.6 V is normal; below 11 V charge or swap the battery."
exec /usr/bin/python3 - <<'PY'
import time
import rclpy
from rclpy.qos import QoSProfile, ReliabilityPolicy
from sensor_msgs.msg import BatteryState

rclpy.init()
node = rclpy.create_node("ofb_volt_pane")
last = {"v": None, "t": 0.0}
node.create_subscription(BatteryState, "/battery_state",
                         lambda m: last.update(v=m.voltage, t=time.time()),
                         QoSProfile(depth=1, reliability=ReliabilityPolicy.BEST_EFFORT))
try:
    while rclpy.ok():
        rclpy.spin_once(node, timeout_sec=1.0)      # at most one message per round
        now = time.time()
        if last["v"] is not None and now - last["t"] < 5.0:
            print("%s  %.2f V" % (time.strftime("%H:%M:%S"), last["v"]), flush=True)
        else:
            print("%s  no /battery_state (bringup not running?)" % time.strftime("%H:%M:%S"), flush=True)
        time.sleep(3.0)
except KeyboardInterrupt:
    pass
PY
