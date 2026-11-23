"""Execute Hanoi moves with Panda joint servos and simulated finger contact."""

from collections.abc import Iterator
from dataclasses import dataclass
from math import ceil

import mujoco
import numpy as np
from factw.env.worlds.hanoi import HanoiState, Move, apply_move, is_legal

from .robot_scene import (
    DISK_RADII,
    DISK_THICKNESS,
    FINGERS,
    PARK,
    PEG_HEIGHT,
    PEG_Y,
    TIP_SITE,
    TRANSIT_Z,
    build_model,
    peg_position,
)

_FPS = 30
_FINGER_OPEN = 255.0
_TARGET_QUATERNION = np.array([0.0, 1.0, 0.0, 0.0])
_ARM_JOINTS = tuple(f"joint{i}" for i in range(1, 8))


class TransferError(RuntimeError):
    """A physical transfer could not be completed and verified."""


@dataclass(frozen=True)
class ArmSample:
    phase: str
    control: tuple[float, ...]
    time: float
    grasped: bool


class RobotHanoi:
    def __init__(self, width=1280, height=720):
        self.model = build_model()
        self.data = mujoco.MjData(self.model)
        self.width = width
        self.height = height
        self._renderer = None
        self._render_options = mujoco.MjvOption()
        self._render_options.geomgroup[3] = 0
        self._ik = mujoco.MjData(self.model)
        self._arm_qpos = np.array([self.model.joint(name).qposadr[0] for name in _ARM_JOINTS])
        self._arm_dof = np.array([self.model.joint(name).dofadr[0] for name in _ARM_JOINTS])
        self._limits = np.array([self.model.joint(name).range for name in _ARM_JOINTS])
        self._tip = self.model.site(TIP_SITE).id
        self._disk_ids = [
            self.model.body(f"hanoi_disk_{disk}").id for disk in range(len(DISK_RADII))
        ]
        self._finger_ids = {self.model.body(name).id for name in FINGERS}
        self._disk_set = set(self._disk_ids)
        self.reset()

    def reset(self, pegs=(0, 0, 0)):
        mujoco.mj_resetDataKeyframe(self.model, self.data, self.model.key("home").id)
        board = HanoiState(pegs)
        if len(board.pegs) != len(self._disk_ids):
            raise ValueError("The Panda board requires three disk positions")
        for disk, peg in enumerate(board.pegs):
            below = pegs[disk + 1 :].count(peg)
            joint = self.data.joint(f"hanoi_disk_{disk}_joint")
            joint.qpos[:3] = peg_position(peg, DISK_THICKNESS * (below + 0.5))
        mujoco.mj_forward(self.model, self.data)
        self._point = np.array(PARK)
        angles = self._angles_for(self._point)
        self.data.qpos[self._arm_qpos] = self.data.ctrl[:7] = angles
        self._finger_command = self.data.ctrl[7] = _FINGER_OPEN
        mujoco.mj_forward(self.model, self.data)
        for _ in range(120):
            mujoco.mj_step(self.model, self.data)
        self.data.time = 0.0
        return self.settled_state()

    def _angles_for(self, target):
        model, pose, tip = self.model, self._ik, self._tip
        pose.qpos[:] = self.data.qpos
        pose.qpos[self._arm_qpos] = self.data.ctrl[:7]
        linear, angular = np.empty((3, model.nv)), np.empty((3, model.nv))
        quaternion, inverse, relative, rotation_error = (
            np.empty(4),
            np.empty(4),
            np.empty(4),
            np.empty(3),
        )
        for _ in range(65):
            mujoco.mj_kinematics(model, pose)
            mujoco.mj_comPos(model, pose)
            translation = target - pose.site_xpos[tip]
            mujoco.mju_mat2Quat(quaternion, pose.site_xmat[tip])
            mujoco.mju_negQuat(inverse, quaternion)
            mujoco.mju_mulQuat(relative, _TARGET_QUATERNION, inverse)
            mujoco.mju_quat2Vel(rotation_error, relative, 1)
            if np.linalg.norm(translation) < 2e-5 and np.linalg.norm(rotation_error) < 1e-4:
                return pose.qpos[self._arm_qpos]
            mujoco.mj_jacSite(model, pose, linear, angular, tip)
            jacobian = np.vstack((linear[:, self._arm_dof], angular[:, self._arm_dof]))
            error = np.concatenate((translation, rotation_error))
            delta = jacobian.T @ np.linalg.solve(jacobian @ jacobian.T + 1e-4 * np.eye(6), error)
            pose.qpos[self._arm_qpos] = np.clip(
                pose.qpos[self._arm_qpos] + np.clip(delta, -0.18, 0.18),
                self._limits[:, 0],
                self._limits[:, 1],
            )
        raise TransferError(f"Panda cannot reach {tuple(map(float, target))}")

    def _contacts(self, disk_ids):
        fingers = set()
        for contact in self.data.contact:
            bodies = set(self.model.geom_bodyid[contact.geom])
            if bodies & disk_ids:
                fingers.update(bodies & self._finger_ids)
        return fingers

    def settled_state(self) -> HanoiState | None:
        if self._contacts(self._disk_set):
            return None
        pegs = tuple(
            int(peg)
            for peg in np.abs(self.data.xpos[self._disk_ids, 1, None] - np.array(PEG_Y)).argmin(
                axis=1
            )
        )
        velocity = np.empty(6)
        for disk, (peg, identifier) in enumerate(zip(pegs, self._disk_ids, strict=True)):
            below = pegs[disk + 1 :].count(peg)
            target = peg_position(peg, DISK_THICKNESS * (below + 0.5))
            position = self.data.xpos[identifier]
            if np.linalg.norm(position[:2] - target[:2]) > 0.0034:
                return None
            if abs(position[2] - target[2]) > 0.0014 or self.data.xmat[identifier, 8] < 0.998:
                return None
            mujoco.mj_objectVelocity(
                self.model, self.data, mujoco.mjtObj.mjOBJ_BODY, identifier, velocity, 0
            )
            if np.linalg.norm(velocity[:3]) > 0.25 or np.linalg.norm(velocity[3:]) > 0.012:
                return None
        return HanoiState(pegs)

    def _motion(self, disk, phase, point, finger, duration) -> Iterator[ArmSample]:
        start, end = self._point, np.array(point)
        initial = self._finger_command
        ticks_per_frame = round(1.0 / (_FPS * self.model.opt.timestep))
        disk_id = {self._disk_ids[disk]}
        is_motion = not np.array_equal(start, end)
        frames = ceil(duration * _FPS)
        for frame in range(1, frames + 1):
            progress = frame / frames
            ease = progress**2 * (3 - 2 * progress)
            self._point = start + (end - start) * ease
            if is_motion:
                self.data.ctrl[:7] = self._angles_for(self._point)
            self._finger_command = self.data.ctrl[7] = initial + (finger - initial) * ease
            for _ in range(ticks_per_frame):
                mujoco.mj_step(self.model, self.data)
            yield ArmSample(
                phase,
                tuple(map(float, self.data.ctrl)),
                float(self.data.time),
                self._contacts(disk_id) == self._finger_ids,
            )

    def move(self, disk: int, target: int) -> Iterator[ArmSample]:
        state = self.settled_state()
        command = Move(disk, target)
        if state is None or not is_legal(state, command):
            raise ValueError("Select a top disk and a legal destination peg")
        expected = apply_move(state, command)
        disk_id = self._disk_ids[disk]
        x, y, pickup_z = self.data.xpos[disk_id]
        source_high = (x, y, TRANSIT_Z)
        source_low = (x, y, pickup_z)
        target_high = peg_position(target, TRANSIT_Z)
        place_z = DISK_THICKNESS * (state.pegs.count(target) + 0.5) + 0.0013
        closed = 255.0 * (DISK_RADII[disk] - 0.006) / 0.04
        transfer_duration = 0.65 + 3 * abs(target_high[1] - y)
        for phase, point, finger, duration in (
            ("Approach", source_high, _FINGER_OPEN, 0.62),
            ("Lower", source_low, _FINGER_OPEN, 0.81),
            ("Lower", source_low, _FINGER_OPEN, 0.32),
            ("Grasp", source_low, closed, 0.67),
            ("Lift", source_high, closed, 0.83),
            ("Transfer", target_high, closed, transfer_duration),
            ("Align", target_high, closed, 0.33),
        ):
            yield from self._motion(disk, phase, point, finger, duration)
            held = self._contacts({disk_id}) == self._finger_ids
            if phase == "Grasp" and not held:
                raise TransferError(f"Both fingers must contact disk {disk} before lifting")
            if phase in {"Lift", "Transfer", "Align"}:
                if self.data.xpos[disk_id, 2] <= PEG_HEIGHT or not held:
                    raise TransferError(f"Disk {disk} did not clear the pegs while held")

        tip_offset = self.data.site_xpos[self._tip] - self.data.xpos[disk_id]
        aligned = np.array(target_high) + tip_offset
        placement = aligned - (0, 0, TRANSIT_Z - place_z)
        for phase, point, finger, duration in (
            ("Align", aligned, closed, 0.36),
            ("Place", placement, closed, 0.85),
            ("Place", placement, closed, 0.32),
        ):
            yield from self._motion(disk, phase, point, finger, duration)
        # The held ring can shift relative to the fingers as the arm descends.
        centered = placement.copy()
        centered[:2] += np.array(target_high[:2]) - self.data.xpos[disk_id, :2]
        for phase, point, finger, duration in (
            ("Place", centered, closed, 0.36),
            ("Release", centered, _FINGER_OPEN, 0.33),
            ("Retreat", aligned, _FINGER_OPEN, 0.75),
            ("Retreat", PARK, _FINGER_OPEN, 0.59),
            ("Settle", PARK, _FINGER_OPEN, 0.22),
        ):
            yield from self._motion(disk, phase, point, finger, duration)
        if self.settled_state() != expected:
            raise TransferError(f"Disk {disk} did not settle on peg {target}")

    def render(self, camera="overview"):
        if self._renderer is None:
            self._renderer = mujoco.Renderer(self.model, height=self.height, width=self.width)
        self._renderer.update_scene(self.data, camera=camera, scene_option=self._render_options)
        return self._renderer.render().copy()

    def close(self):
        if self._renderer is not None:
            self._renderer.close()
            self._renderer = None
