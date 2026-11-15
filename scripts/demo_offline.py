"""Offline demo in the toy world: no robot, no camera, no ROS.

    python scripts/demo_offline.py --camera depth
    python scripts/demo_offline.py --camera nodepth --seed 3 --figures out/demo

Runs the real ObjectMemory, geometry.observe, and search.find against a
simulated room: patrol, query the blue mug, move it, patrol again, query again.
"""
import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "src"))

from objmem.sim.demo import run_demo  # noqa: E402
from objmem.types import Params  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--camera", choices=["depth", "nodepth"], default="depth",
                    help="depth = RealSense color + depth, nodepth = C920 color only")
    ap.add_argument("--seed", type=int, default=2,
                    help="default 2: the old place ranks first in both camera modes; with other seeds "
                         "the new memory may rank first and the old place is then not visited")
    ap.add_argument("--config", default=None, help="YAML with Params overrides (default: built-in defaults)")
    ap.add_argument("--figures", default=None, help="folder for map PNGs of each step (optional)")
    args = ap.parse_args(argv)
    params = Params.load(args.config) if args.config else None
    run_demo(args.camera, seed=args.seed, params=params, figure_dir=args.figures)
    return 0


if __name__ == "__main__":
    sys.exit(main())
