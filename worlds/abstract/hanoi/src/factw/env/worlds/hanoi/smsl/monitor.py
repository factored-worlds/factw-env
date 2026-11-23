import json
from copy import deepcopy
from dataclasses import asdict

from factw.env.worlds.hanoi import (
    HanoiEnv,
    HanoiOracle,
    HanoiState,
    HanoiTask,
    Move,
)
from factw.env.worlds.hanoi.smsl.definition import BRANCH, OPERATIONS, machine, pegs

import smsl


class HanoiMonitor:
    """Optional private monitor for independently specified three-disk move rules."""

    def __init__(self, task: HanoiTask, scope: str):
        if len(task.start) != 3:
            raise ValueError("Hanoi SMSL monitoring requires exactly three disks")
        self.task = task
        self.machine = machine(task.start)
        self._planner = smsl.Planner(
            {"branch": BRANCH, "expression": self.machine.branch(BRANCH).activation}
        )
        self.snapshot = self.machine.start(smsl.Context(scope, "three-disks", "hanoi_step"))
        self.steps = 0
        self._records: list[dict] = []

    def advance(self, action: Move, outcome: str, step: int) -> None:
        if type(step) is not int or step != self.steps + 1:
            raise ValueError("Monitor steps must follow consecutive engine outcomes")
        if not isinstance(action, Move) or action.disk >= 3:
            raise ValueError("Action must identify one of the three Hanoi disks")
        before = pegs(self.snapshot.facts(BRANCH))
        if self.steps >= self.task.max_steps or before == self.task.goal:
            raise ValueError("Monitored episode has ended; reset before advancing")
        operation = OPERATIONS[action]
        enabled = {item["operations"][BRANCH] for item in self._planner.enabled(self.snapshot)}
        expected = "moved" if operation in enabled else "illegal"
        if outcome != expected:
            raise ValueError(f"Outcome {outcome!r} disagrees with SMSL outcome {expected!r}")
        event = smsl.Event(outcome, step, self.snapshot.context)
        operations = {BRANCH: operation} if outcome == "moved" else {}
        result = (
            self.snapshot.confirm(event, operations) if operations else self.snapshot.advance(event)
        )
        after = pegs(result.snapshot.facts(BRANCH))
        record = {
            "engine_step": step,
            "action": asdict(action),
            "outcome": outcome,
            "event": event.to_dict(),
            "event_ref": {"scope": result.event_ref.scope, "step": result.event_ref.step},
            "operations": operations,
            "changed": list(result.changed),
            "before": list(before),
            "after": list(after),
            "delta": _delta(before, after),
        }
        self.snapshot = result.snapshot
        self.steps = step
        self._records.append(record)

    def reset(self, scope: str) -> None:
        context = self.snapshot.context
        self.snapshot = self.snapshot.reset(smsl.Context(scope, context.subject, context.clock))
        self.steps = 0
        self._records.clear()

    def reference(self) -> dict:
        return {"pegs": list(pegs(self.snapshot.facts(BRANCH)))}

    def check(self, env: HanoiEnv) -> None:
        expected = HanoiOracle().describe(env.state)["pegs"]
        if self.task != env.task or self.steps != env.snapshot().steps:
            raise AssertionError("Engine/SMSL task or step differs")
        if self.reference()["pegs"] != expected:
            raise AssertionError(f"Engine/SMSL facts differ at step {self.steps}")
        if self._records:
            record = self._records[-1]
            before = HanoiState(tuple(record["before"]))
            delta = HanoiOracle().compare(before, env.state)
            if record["delta"] != delta:
                raise AssertionError(f"Engine/SMSL changes differ at step {self.steps}")

    @property
    def records(self) -> list[dict]:
        return deepcopy(self._records)

    def to_json(self) -> str:
        return json.dumps(self._document(), indent=2, allow_nan=False) + "\n"

    @classmethod
    def restore(cls, source: str) -> HanoiMonitor:
        document = json.loads(source, object_pairs_hook=_unique_object)
        if document["format"] != "hanoi-monitor" or document["version"] != "2":
            raise ValueError("Unsupported Hanoi monitor archive")
        task = document["task"]
        if set(task) != {"start", "goal", "max_steps"}:
            raise ValueError("Invalid Hanoi monitor task")
        monitor = cls(
            HanoiTask(tuple(task["start"]), tuple(task["goal"]), task["max_steps"]),
            document["snapshot"]["context"]["scope"],
        )
        env = HanoiEnv(monitor.task)
        for record in document["events"]:
            action = Move(**record["action"])
            result = env.step(action)
            if record["outcome"] != result.outcome:
                raise ValueError("Recorded outcome differs from replayed engine outcome")
            monitor.advance(action, record["outcome"], record["engine_step"])
            monitor.check(env)
        if _canonical(document) != _canonical(monitor._document()):
            raise ValueError("Hanoi monitor archive differs from its replay")
        return monitor

    def _document(self) -> dict:
        return {
            "format": "hanoi-monitor",
            "version": "2",
            "task": asdict(self.task),
            "snapshot": json.loads(self.snapshot.to_json()),
            "events": self.records,
        }


def _delta(before: tuple[int, ...], after: tuple[int, ...]) -> dict:
    changes = [
        {"disk": disk, "source": source, "target": target}
        for disk, (source, target) in enumerate(zip(before, after, strict=True))
        if source != target
    ]
    return {"changed_disks": [change["disk"] for change in changes], "changes": changes}


def _canonical(document: dict) -> str:
    return json.dumps(document, sort_keys=True, allow_nan=False)


def _unique_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate archive member: {key}")
        result[key] = value
    return result
