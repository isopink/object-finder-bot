"""nodepth observations through the real ObjectMemory: the EKF bearing fusion converges."""
import math

import numpy as np
import pytest

from objmem.geometry import make_in_view, observe, project
from objmem.types import Detection, Params, Pose2D

memory = pytest.importorskip("objmem.memory")

TARGET = np.array([2.0, 1.5, 0.75])
EMB = np.ones(512, dtype=np.float32) / math.sqrt(512.0)


def _facing(x, y, offset=0.0):
    return Pose2D(x, y, math.atan2(TARGET[1] - y, TARGET[0] - x) + offset)


def _detect(pose, params):
    u, v, _ = project(TARGET, pose, params)
    return Detection(box=(u - 15, v - 15, u + 15, v + 15), label="mug", conf=0.9, embedding=EMB)


@pytest.mark.parametrize("rounds", [1, 3])
def test_nodepth_three_poses_converge(rounds):
    params = Params()
    params.camera_mode = "nodepth"
    poses = [_facing(0.3, 0.2, 0.1), _facing(3.6, 0.0, -0.15), _facing(1.6, 3.4, 0.05)]
    mem = memory.ObjectMemory(params)
    in_view = make_in_view(params)
    errors = []
    variances = []
    t = 1000.0
    for _ in range(rounds):
        for pose in poses:
            obs = observe(_detect(pose, params), pose, params, t)
            assert obs is not None and obs.bearing is not None
            mem.update_frame([obs], pose, in_view, t)
            assert len(mem.items) == 1, "bearing observations of one object must fuse into one memory"
            item = mem.items[0]
            errors.append(float(np.linalg.norm(item.mu - TARGET[:2])))
            variances.append(float(np.linalg.eigvalsh(item.cov)[-1]))
            t += 1.0
    assert errors[-1] < errors[0]
    assert variances[-1] < variances[0]
    assert errors[-1] < 0.02
    assert mem.items[0].n_obs == 3 * rounds
