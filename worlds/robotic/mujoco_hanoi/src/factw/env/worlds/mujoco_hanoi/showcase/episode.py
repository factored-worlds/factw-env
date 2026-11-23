"""Select a reproducible board and tower goal for the Panda agent."""

from dataclasses import dataclass
from itertools import product
from random import Random
from secrets import randbelow

from factw.env.worlds.hanoi import HanoiTask

SEED_LIMIT = 2**31
_BOARDS = tuple(
    (start, (target,) * 3)
    for start in product(range(3), repeat=3)
    for target in range(3)
    if target != start[-1]
)


@dataclass(frozen=True)
class Episode:
    task: HanoiTask = HanoiTask()
    seed: int | None = None

    @classmethod
    def sample(cls, seed=None):
        if seed is None:
            seed = randbelow(SEED_LIMIT)
        if type(seed) is not int or not 0 <= seed < SEED_LIMIT:
            raise ValueError(f"seed must be an integer from 0 to {SEED_LIMIT - 1}")
        start, goal = Random(seed).choice(_BOARDS)
        return cls(HanoiTask(start, goal), seed)

    def metadata(self):
        return {
            "seed": self.seed,
            "sampling_profile": "legal-board-to-tower-v1" if self.seed is not None else "tutorial",
            "start": self.task.start,
            "goal": self.task.goal,
        }
