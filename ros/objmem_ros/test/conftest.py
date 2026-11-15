import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
# objmem_ros (package root) and this folder (fake_worker) without a colcon build.
for p in (os.path.dirname(HERE), HERE):
    if p not in sys.path:
        sys.path.insert(0, p)
