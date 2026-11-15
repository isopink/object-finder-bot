"""Shared by the unit tests and the ROS end-to-end test."""
import numpy as np

from objmem.types import Observation, Pose2D

from fake_worker import EMB_A, EMB_B

POS_A = (2.0, 0.0)
POS_B = (-2.0, 1.0)


def preload(memory, t):
    """Two memories: A at POS_A (best match for the fake query), B at POS_B."""
    pose = Pose2D(0.0, 0.0, 0.0)
    cov = np.diag([0.01, 0.01])
    obs = [
        Observation(embedding=EMB_A.copy(), mu=np.array(POS_A), cov=cov.copy(), t=t,
                    view_pose=Pose2D(1.0, 0.0, 0.0), label="mug"),
        Observation(embedding=EMB_B.copy(), mu=np.array(POS_B), cov=cov.copy(), t=t,
                    view_pose=Pose2D(-1.0, 1.0, 3.14159), label="mug"),
    ]
    memory.update_frame(obs, pose, lambda mu, p: False, t)
    return memory
