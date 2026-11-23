"""Record the board and Panda transfer together in a native State Language World."""

from dataclasses import replace
from functools import cache
from importlib.resources import files

import smsl
from factw.env.worlds.hanoi.smsl.definition import BRANCH, FACTS, OPERATIONS, machine
from smsl import definition as d

DISKS = ("small", "medium", "large")


@cache
def robot_machine(start, goal):
    board = smsl.Definition.from_machine(machine(start))
    (branch,) = board.branches
    small, medium, large = (
        d.Binary("eq", d.Read("self", fact), d.Literal("abc"[peg]))
        for fact, peg in zip(FACTS, goal, strict=True)
    )
    solved = d.Predicate("Solved", d.Binary("and", d.Binary("and", small, medium), large))
    branch = replace(branch, named_states=(solved,))
    source = files(__package__).joinpath("transfer.smsl").read_text(encoding="utf-8")
    robot = smsl.Definition.from_machine(smsl.loads(source))
    return smsl.compile(
        replace(
            board,
            branches=(branch, *robot.branches),
            events=board.events + robot.events,
        )
    )


class RobotMonitor:
    def __init__(self, start, goal, scope):
        self.world = smsl.World()
        self.snapshot = self.world.spawn(
            "panda",
            robot_machine(start, goal),
            smsl.Context(scope, "panda-hanoi", "fact_update"),
        )

    @property
    def facts(self):
        return self.snapshot.facts(BRANCH) | self.snapshot.facts("Robot")

    def update(self, name, payload, *, placed=None):
        before = self.facts
        event = smsl.Event(name, self.snapshot.step + 1, self.snapshot.context, payload=payload)
        if placed is None:
            result = self.world.advance("panda", event)
        else:
            result = self.world.confirm(
                "panda",
                event,
                {BRANCH: OPERATIONS[placed], "Robot": "confirm_placement"},
            )
        self.snapshot = result.snapshot
        after = self.facts
        return {
            "fact_step": self.snapshot.step,
            "facts": after,
            "changes": {
                key: (before[key], value) for key, value in after.items() if before[key] != value
            },
        }
