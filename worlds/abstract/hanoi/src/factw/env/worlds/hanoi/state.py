from dataclasses import dataclass


@dataclass(frozen=True)
class HanoiState:
    """Peg location per disk, ordered smallest to largest."""

    pegs: tuple[int, ...]

    def __post_init__(self):
        if not isinstance(self.pegs, tuple) or not self.pegs:
            raise ValueError("pegs must be a nonempty tuple")
        if any(type(peg) is not int or peg not in range(3) for peg in self.pegs):
            raise ValueError("each peg must be 0, 1, or 2")


@dataclass(frozen=True)
class Move:
    disk: int
    target: int

    def __post_init__(self):
        if type(self.disk) is not int or self.disk < 0:
            raise ValueError("disk must be a nonnegative integer")
        if type(self.target) is not int or self.target not in range(3):
            raise ValueError("target must be 0, 1, or 2")


@dataclass(frozen=True)
class HanoiTask:
    start: tuple[int, ...] = (0, 0, 0)
    goal: tuple[int, ...] = (2, 2, 2)
    max_steps: int = 100

    def __post_init__(self):
        HanoiState(self.start)
        HanoiState(self.goal)
        if len(self.start) != len(self.goal):
            raise ValueError("start and goal must have the same disk count")
        if type(self.max_steps) is not int or self.max_steps < 1:
            raise ValueError("max_steps must be a positive integer")
