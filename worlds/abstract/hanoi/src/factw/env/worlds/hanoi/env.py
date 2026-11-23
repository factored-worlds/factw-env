from dataclasses import dataclass

from factw.env.core.core import Observation, StepResult
from factw.env.worlds.hanoi.render import render
from factw.env.worlds.hanoi.rules import apply_move, is_legal
from factw.env.worlds.hanoi.state import HanoiState, HanoiTask, Move
from factw.env.worlds.hanoi.style import DEFAULT_STYLE, RenderStyle

DEFAULT_TASK = HanoiTask()


@dataclass(frozen=True)
class HanoiSnapshot:
    task: HanoiTask
    state: HanoiState
    steps: int
    style: RenderStyle = DEFAULT_STYLE


class HanoiEnv:
    """Discrete moves with rendered observations; illegal attempts consume a step."""

    def __init__(self, task: HanoiTask = DEFAULT_TASK, *, style: RenderStyle = DEFAULT_STYLE):
        self.task = task
        self.style = style
        self.reset()

    @property
    def state(self) -> HanoiState:
        return self._state

    @property
    def terminated(self) -> bool:
        return self.state.pegs == self.task.goal

    @property
    def truncated(self) -> bool:
        return self._steps >= self.task.max_steps and not self.terminated

    def reset(self, *, seed: int = 0) -> Observation:
        if type(seed) is not int:
            raise ValueError("seed must be an integer")
        self._state = HanoiState(self.task.start)
        self._steps = 0
        return self.observe()

    def observe(self) -> Observation:
        return Observation(rgb=render(self.state.pegs, self.style))

    def step(self, move: Move) -> StepResult:
        if self.terminated or self.truncated:
            raise RuntimeError("episode has ended; call reset")
        legal = is_legal(self.state, move)
        if legal:
            self._state = apply_move(self.state, move)
        self._steps += 1
        return StepResult(
            observation=self.observe(),
            reward=float(self.terminated),
            terminated=self.terminated,
            truncated=self.truncated,
            elapsed_seconds=0.0,
            outcome="moved" if legal else "illegal",
        )

    def snapshot(self) -> HanoiSnapshot:
        return HanoiSnapshot(self.task, HanoiState(self.state.pegs), self._steps, self.style)

    def restore(self, snapshot: HanoiSnapshot) -> None:
        if snapshot.task != self.task:
            raise ValueError("snapshot belongs to a different task")
        if len(snapshot.state.pegs) != len(self.task.start):
            raise ValueError("snapshot disk count does not match task")
        if type(snapshot.steps) is not int or not 0 <= snapshot.steps <= self.task.max_steps:
            raise ValueError("invalid snapshot step count")
        self._state = HanoiState(snapshot.state.pegs)
        self._steps = snapshot.steps
        self.style = snapshot.style
