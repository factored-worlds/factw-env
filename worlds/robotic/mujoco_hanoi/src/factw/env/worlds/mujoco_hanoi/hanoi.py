"""MuJoCo Hanoi with actuator control and pose-derived task evaluation."""

from dataclasses import dataclass

import mujoco
import numpy as np
from factw.env.core.core import Observation, StepResult
from factw.env.worlds.hanoi import HanoiState, HanoiTask
from factw.env.worlds.mujoco_hanoi.camera import Camera
from factw.env.worlds.mujoco_hanoi.scene import HOME, model_xml
from factw.env.worlds.mujoco_hanoi.state import physical_state


@dataclass(frozen=True)
class Control:
    x: float
    y: float
    z: float
    grip: float

    def array(self) -> np.ndarray:
        return np.array((self.x, self.y, self.z, self.grip, self.grip), dtype=float)


@dataclass(frozen=True)
class Snapshot:
    task: HanoiTask
    config: tuple[float, int]
    integration_state: np.ndarray
    steps: int
    stable_steps: int
    last_state: HanoiState | None


_DEFAULT_TASK = HanoiTask()


class MujocoHanoiEnv:
    def __init__(
        self,
        task: HanoiTask = _DEFAULT_TASK,
        *,
        camera: bool = True,
        width: int = 320,
        height: int = 240,
        control_dt: float = 0.04,
        max_control_steps: int = 10000,
    ):
        if not 1 <= len(task.start) <= 5:
            raise ValueError("The gantry supports one to five disks")
        if width < 1 or height < 1 or width > 640 or height > 480:
            raise ValueError("Camera dimensions must fit the 640 by 480 framebuffer")
        if not np.isfinite(control_dt) or control_dt <= 0:
            raise ValueError("control_dt must be positive and finite")
        if max_control_steps < 1:
            raise ValueError("max_control_steps must be positive")
        self.task, self.camera = task, camera
        self.width, self.height = width, height
        self.model = mujoco.MjModel.from_xml_string(model_xml(task.start))
        self.data = mujoco.MjData(self.model)
        self.substeps = round(control_dt / self.model.opt.timestep)
        if self.substeps < 1 or not np.isclose(self.substeps * self.model.opt.timestep, control_dt):
            raise ValueError("control_dt must be a multiple of the physics timestep (0.002 s)")
        self.control_dt, self.max_control_steps = control_dt, max_control_steps
        self._joint_ids = [self.model.joint(name).id for name in ("x", "y", "z", "left", "right")]
        self._qpos_ids = self.model.jnt_qposadr[self._joint_ids]
        self._qvel_ids = self.model.jnt_dofadr[self._joint_ids]
        self._disk_ids = [self.model.body(f"disk_{i}").id for i in range(len(task.start))]
        self._finger_ids = {self.model.body(name).id for name in ("finger_left", "finger_right")}
        self._camera = Camera(self.model, width, height) if camera else None
        self._closed = False
        self.steps = self.stable_steps = 0
        self._last_state = None
        self._state_spec = mujoco.mjtState.mjSTATE_INTEGRATION

    def reset(self, *, seed: int = 0) -> Observation:
        self._check_open()
        if type(seed) is not int:
            raise ValueError("seed must be an integer")
        mujoco.mj_resetData(self.model, self.data)
        self.data.qpos[self._qpos_ids] = Control(*HOME).array()
        self.data.ctrl[:] = Control(*HOME).array()
        for _ in range(150):
            mujoco.mj_step(self.model, self.data)
        mujoco.mj_forward(self.model, self.data)
        self.steps = self.stable_steps = 0
        self._last_state = self.physical_state()
        self.stable_steps = 5 if self._last_state is not None else 0
        return self.observe()

    def step(self, control: Control) -> StepResult:
        self._check_open()
        if self.steps >= self.max_control_steps or self.solved:
            raise RuntimeError("Episode has ended; reset before stepping again")
        values = control.array()
        if not np.isfinite(values).all():
            raise ValueError("Control values must be finite")
        bounds = self.model.actuator_ctrlrange
        if np.any(values < bounds[:, 0]) or np.any(values > bounds[:, 1]):
            raise ValueError("Control outside the gantry workspace or gripper range")
        self.data.ctrl[:] = values
        for _ in range(self.substeps):
            mujoco.mj_step(self.model, self.data)
        mujoco.mj_forward(self.model, self.data)
        self.steps += 1
        state = self.physical_state()
        self.stable_steps = (
            self.stable_steps + 1 if state is not None and state == self._last_state else 0
        )
        self._last_state = state
        terminated = self.solved
        truncated = self.steps >= self.max_control_steps and not terminated
        return StepResult(
            self.observe(),
            float(terminated),
            terminated,
            truncated,
            self.control_dt,
            "solved" if terminated else ("time_limit" if truncated else "running"),
        )

    @property
    def solved(self) -> bool:
        return self.stable_steps >= 5 and self._last_state == HanoiState(self.task.goal)

    def physical_state(self) -> HanoiState | None:
        return physical_state(self.model, self.data, self._disk_ids, self._finger_ids)

    def observe(self) -> Observation:
        self._check_open()
        rgb = np.empty((0, 0, 3), dtype=np.uint8)
        depth = None
        if self._camera is not None:
            rgb, depth = self._camera.capture(self.data)
        proprioception = np.concatenate(
            (self.data.qpos[self._qpos_ids], self.data.qvel[self._qvel_ids])
        )
        return Observation(rgb, depth, proprioception)

    def snapshot(self) -> Snapshot:
        self._check_open()
        state = np.empty(mujoco.mj_stateSize(self.model, self._state_spec))
        mujoco.mj_getState(self.model, self.data, state, self._state_spec)
        return Snapshot(
            self.task,
            (self.control_dt, self.max_control_steps),
            state,
            self.steps,
            self.stable_steps,
            self._last_state,
        )

    def restore(self, snapshot: Snapshot) -> Observation:
        self._check_open()
        if snapshot.task != self.task or snapshot.config != (
            self.control_dt,
            self.max_control_steps,
        ):
            raise ValueError("Snapshot belongs to a different task")
        if snapshot.integration_state.shape != (mujoco.mj_stateSize(self.model, self._state_spec),):
            raise ValueError("Snapshot does not match this model")
        mujoco.mj_setState(self.model, self.data, snapshot.integration_state, self._state_spec)
        mujoco.mj_forward(self.model, self.data)
        self.steps, self.stable_steps = snapshot.steps, snapshot.stable_steps
        self._last_state = snapshot.last_state
        return self.observe()

    def close(self) -> None:
        if self._camera is not None:
            self._camera.close()
        self._closed = True

    def _check_open(self) -> None:
        if self._closed:
            raise RuntimeError("Environment is closed")

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
