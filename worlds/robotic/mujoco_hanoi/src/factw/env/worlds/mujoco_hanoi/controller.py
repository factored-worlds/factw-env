"""Privileged scripted demonstrations emitted as ordinary actuator controls."""

from collections.abc import Iterator
from math import ceil

import numpy as np
from factw.env.core.core import StepResult
from factw.env.worlds.hanoi import HanoiState, Move, apply_move, is_legal, solve
from factw.env.worlds.mujoco_hanoi.hanoi import Control, MujocoHanoiEnv
from factw.env.worlds.mujoco_hanoi.scene import PEG_X, SAFE_Z, THICKNESS, radius


class GantryController:
    def __init__(self, env: MujocoHanoiEnv):
        self.env = env

    def _go(self, target: Control, seconds: float) -> Iterator[tuple[Control, StepResult]]:
        start = self.env.data.ctrl[[0, 1, 2, 3]].copy()
        destination = np.array((target.x, target.y, target.z, target.grip))
        for fraction in np.linspace(0, 1, max(2, ceil(seconds / self.env.control_dt)) + 1)[1:]:
            control = Control(*map(float, start + (destination - start) * fraction))
            result = self.env.step(control)
            yield control, result
            if result.terminated or result.truncated:
                return

    def move(self, move: Move) -> Iterator[tuple[Control, StepResult]]:
        state = self.env.physical_state()
        if state is None or not is_legal(state, move):
            raise ValueError("Demonstration requires a settled state and a legal Hanoi move")
        source = state.pegs[move.disk]
        pickup_z = THICKNESS * (sum(p == source for p in state.pegs) - 0.5)
        place_z = THICKNESS * (sum(p == move.target for p in state.pegs) + 0.5) + 0.001
        open_gap, closed_gap = radius(move.disk) + 0.02, radius(move.disk) + 0.001
        source_x, target_x = PEG_X[source], PEG_X[move.target]
        stages = (
            (
                Control(float(self.env.data.ctrl[0]), float(self.env.data.ctrl[1]), SAFE_Z, 0.15),
                0.5,
            ),
            (Control(source_x, 0, SAFE_Z, open_gap), 1.6),
            (Control(source_x, 0, pickup_z, open_gap), 1.7),
            (Control(source_x, 0, pickup_z, closed_gap), 0.5),
            (Control(source_x, 0, SAFE_Z, closed_gap), 1.8),
            (Control(target_x, 0, SAFE_Z, closed_gap), 2.2),
            (Control(target_x, 0, place_z, closed_gap), 1.8),
            (Control(target_x, 0, place_z, open_gap), 0.5),
            (Control(target_x, 0, SAFE_Z, open_gap), 1.7),
            (Control(target_x, 0, SAFE_Z, open_gap), 0.4),
        )
        for control, duration in stages:
            for sample in self._go(control, duration):
                yield sample
                if sample[1].terminated or sample[1].truncated:
                    return
        if self.env.physical_state() != apply_move(state, move):
            raise RuntimeError(f"Physical placement failed for {move}: {self.env.physical_state()}")

    def solve(self) -> Iterator[tuple[Control, StepResult]]:
        state = self.env.physical_state()
        if state is None:
            raise ValueError("Planning requires a settled Hanoi state")
        for move in solve(state, HanoiState(self.env.task.goal)):
            for sample in self.move(move):
                yield sample
                if sample[1].terminated or sample[1].truncated:
                    return
