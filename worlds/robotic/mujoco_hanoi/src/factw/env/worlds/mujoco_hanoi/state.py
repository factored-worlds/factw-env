"""Privileged symbolic annotation from contact, pose, and velocity.

An airborne, moving, tilted, illegally stacked, or gripped disk has no settled
Hanoi assignment. These annotations never enter camera/proprioception inputs.
"""

import mujoco
import numpy as np
from factw.env.worlds.hanoi import HanoiState
from factw.env.worlds.mujoco_hanoi.scene import PEG_X, THICKNESS


def physical_state(model, data, disk_ids, finger_ids) -> HanoiState | None:
    for contact in data.contact:
        bodies = set(model.geom_bodyid[contact.geom])
        if bodies & finger_ids and bodies.intersection(disk_ids):
            return None
    positions = data.xpos[disk_ids]
    peg_indices = np.abs(positions[:, 0, None] - np.array(PEG_X)).argmin(axis=1)
    for disk, peg in enumerate(peg_indices):
        pos = positions[disk]
        if np.linalg.norm(pos[:2] - (PEG_X[peg], 0)) > 0.006:
            return None
        below = sum(other == peg for other in peg_indices[disk + 1 :])
        if abs(pos[2] - THICKNESS * (below + 0.5)) > 0.003:
            return None
        if data.xmat[disk_ids[disk], 8] < 0.995:
            return None
        velocity = np.empty(6)
        mujoco.mj_objectVelocity(model, data, mujoco.mjtObj.mjOBJ_BODY, disk_ids[disk], velocity, 0)
        if np.linalg.norm(velocity) > 0.035:
            return None
    return HanoiState(tuple(map(int, peg_indices)))
