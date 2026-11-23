"""Apply registered effects after native execution admission and fresh capture checks."""

import json
from dataclasses import dataclass
from math import isfinite
from uuid import uuid4

import smsl

from ..bindings.button_primitives import (
    BUTTONS,
    TICS_PER_SIMULATED_SECOND,
    ButtonBindings,
    validate_button_composition,
)
from ..information.player_observation import PlayerObservation, player_observation


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _limit(value, maximum, name):
    if type(value) is not int or not 1 <= value <= maximum:
        raise ValueError(f"{name} must be between 1 and {maximum}")
    return value


@dataclass(frozen=True)
class PrimitiveAdmission:
    admission_id: str
    episode_id: str
    capture_id: str
    block: str
    ticket_id: int
    native_command: str
    basis: str

    def __post_init__(self):
        if (
            type(self.ticket_id) is not int
            or not 0 < self.ticket_id < 2**64
            or any(
                type(value) is not str or not value
                for value in (
                    self.admission_id,
                    self.episode_id,
                    self.capture_id,
                    self.block,
                    self.native_command,
                    self.basis,
                )
            )
        ):
            raise ValueError("A native admission requires exact typed identifiers and ticket")


@dataclass(frozen=True)
class PrimitiveReceipt:
    command_status: str
    admission: PrimitiveAdmission
    command: dict | None
    native_result: object = None


class PrimitiveExecution:
    """Own the native scheduler; expose no native environment to a provider."""

    def __init__(
        self,
        definition,
        world,
        environment,
        bindings,
        *,
        episode_id,
        episode_limit=500,
        skill_limit=80,
    ):
        if type(episode_id) is not str or not episode_id:
            raise ValueError("A primitive execution requires an episode identity")
        if not isinstance(bindings, ButtonBindings):
            raise TypeError("Primitive bindings must be explicitly registered")
        configuration = environment.metadata.get("configuration", {})
        if environment.metadata.get("backend") != "vizdoom":
            raise ValueError("Primitive execution requires the ViZDoom button adapter")
        native_buttons = environment.metadata.get("buttons", [])
        if (
            len(native_buttons) != len(BUTTONS)
            or {item["name"] for item in native_buttons} != set(BUTTONS)
            or any(item["kind"] != "binary" or item["maximum"] != 1 for item in native_buttons)
        ):
            raise ValueError(
                "Native configuration must expose exactly the seven binary player buttons"
            )
        self.max_tics_per_dispatch = _limit(configuration.get("frame_skip"), 4, "frame_skip")
        self.episode_limit = _limit(episode_limit, 500, "episode_limit")
        self.skill_limit = _limit(skill_limit, 80, "skill_limit")
        self.episode_id = episode_id
        self._definition = definition.to_dict()
        self._blocks = self._definition["blocks"]
        validate_button_composition(self._definition, world, bindings)
        self._execution = smsl.ExecutionSession(definition, world)
        self._environment, self._bindings = environment, bindings
        self._capture_id = None
        self._latest_capture_id = None
        self._seen_captures = set()
        self._admissions = {}
        self._latest = {}
        self._pending = {}
        self._cancelling = set()
        self._spent = set()
        self._times = {}
        self._skill_counts = {}
        self.dispatch_count = 0
        self.failed = False
        self._retired = False
        self.last_receipt = None

    def _ready(self):
        if self._retired:
            raise RuntimeError("Primitive execution was replaced; use the active reviewed handle")
        if self.failed:
            raise RuntimeError("Primitive execution failed; do not continue the episode")

    def retire(self):
        """Invalidate a quiescent handle after constructing its reviewed replacement."""
        self._ready()
        if (
            self.dispatch_count
            or self._pending
            or self._cancelling
            or self.inspect()["status"] not in {"idle", "success", "failure"}
        ):
            raise ValueError("Only quiescent execution without native effects can be replaced")
        self._retired = True
        self._capture_id = self._latest_capture_id = None
        self._admissions.clear()
        self._latest.clear()

    def _capture(self, capture_id):
        self._ready()
        if type(capture_id) is not str or not capture_id or capture_id in self._seen_captures:
            raise ValueError("Capture identities must be new within this episode")
        self._seen_captures.add(capture_id)
        self._latest_capture_id = capture_id
        self._capture_id = None

    @property
    def latest_capture_id(self):
        return self._latest_capture_id

    def capture(self, observation):
        if not isinstance(observation, PlayerObservation):
            raise TypeError("Primitive admission accepts only the detached player observation")
        player_observation(observation, capture_id=observation.capture_id)
        self._capture(observation.capture_id)
        self._capture_id = observation.capture_id

    def missing_capture(self, capture_id):
        self._capture(capture_id)

    def observe(self, instance, event):
        self._ready()
        if event.name in {"command_applied", "command_failed"}:
            raise ValueError("Command outcomes enter only through exact native ticket completion")
        report = self._execution.observe(instance, event)
        self._times[instance] = event.time
        return report

    def validate_observation_time(self, time, instances):
        self._ready()
        if (
            type(time) is not int
            or not 0 <= time < 2**64
            or any(time < self._times.get(instance, 0) for instance in instances)
        ):
            raise ValueError("Observation time precedes its native execution clock")

    def _basis(self, instance):
        return _json(smsl.snapshot_basis(self._execution.world().snapshot(instance)))

    def tick(self, times, *, budget=1000):
        self._ready()
        if self._capture_id is None:
            raise ValueError(
                "Native primitive admission requires an available current player capture"
            )
        report = self._execution.tick(times, budget=budget)
        self._times.update(times)
        for block, state in report["states"].items():
            if state in {"idle", "success", "failure"}:
                self._skill_counts.pop(block, None)
        admissions = []
        for command in report["commands"]:
            block = command["block"]
            if command["kind"] == "cancel":
                self._cancelling.add((block, command["ticket"]["id"]))
                continue
            self._pending[block] = command
        for block, command in self._pending.items():
            if (block, command["ticket"]["id"]) in self._cancelling:
                continue
            specification = self._blocks[block]
            world = self._execution.world()
            if report["states"][block] != "running" or not world.action_applicable(
                specification["instance"],
                specification["branch"],
                specification["action"],
                specification["arguments"],
            ):
                continue
            instance = self._blocks[block]["instance"]
            admission = PrimitiveAdmission(
                uuid4().hex,
                self.episode_id,
                self._capture_id,
                block,
                command["ticket"]["id"],
                _json(command),
                self._basis(instance),
            )
            self._admissions[admission.admission_id] = admission
            self._latest[block] = admission.admission_id
            admissions.append(admission)
        return report, tuple(admissions)

    def _validate(self, admission):
        self._ready()
        if (
            not isinstance(admission, PrimitiveAdmission)
            or self._admissions.get(admission.admission_id) is not admission
            or self._latest.get(admission.block) != admission.admission_id
            or admission.admission_id in self._spent
        ):
            raise ValueError("Dispatch requires an exact unused native admission")
        block = self._blocks[admission.block]
        if (
            admission.episode_id != self.episode_id
            or self._capture_id is None
            or admission.capture_id != self._capture_id
            or admission.basis != self._basis(block["instance"])
        ):
            raise ValueError("Primitive episode, capture or current model basis is stale")
        inspection = self._execution.inspect()
        if (
            (admission.block, admission.ticket_id) in self._cancelling
            or inspection["states"][admission.block] != "running"
            or inspection["status"] == "cancelling"
        ):
            raise ValueError("Native primitive ticket is no longer admitted for effects")
        world = self._execution.world()
        if not world.action_applicable(
            block["instance"], block["branch"], block["action"], block["arguments"]
        ):
            raise ValueError("The current primitive guard is false or unknown")
        return block, inspection

    def _ancestors(self, target):
        def contains(name):
            block = self._blocks[name]
            children = block.get("members", [block["member"]] if "member" in block else [])
            return target in children or any(contains(child) for child in children)

        return tuple(
            name for name in self._blocks if name != self._definition["root"] and contains(name)
        )

    def dispatch(self, admission, *, time):
        block, inspection = self._validate(admission)
        command = self._bindings.resolve(admission.block).as_dict()
        if (
            type(time) is not int
            or not 0 <= time < 2**64
            or time < self._times.get(block["instance"], 0)
        ):
            raise ValueError("Primitive completion time precedes its native execution clock")
        if self._environment.terminated or self._environment.truncated:
            raise ValueError("An ended episode cannot accept button effects")
        ancestors = [
            name
            for name in self._ancestors(admission.block)
            if inspection["states"][name] == "running"
        ]
        if self.dispatch_count >= self.episode_limit:
            raise ValueError("Episode primitive dispatch budget is exhausted")
        if any(self._skill_counts.get(name, 0) >= self.skill_limit for name in ancestors):
            raise ValueError("An active nonroot skill dispatch budget is exhausted")
        self._spent.add(admission.admission_id)
        self.dispatch_count += 1
        for name in ancestors:
            self._skill_counts[name] = self._skill_counts.get(name, 0) + 1
        applied = False
        result = None
        self.failed = True
        try:
            result = self._environment.step(command)
            elapsed = result.elapsed_seconds
            if (
                type(elapsed) not in (int, float)
                or not isfinite(elapsed)
                or not 0 <= elapsed <= self.max_tics_per_dispatch / TICS_PER_SIMULATED_SECOND
            ):
                raise ValueError("Native adapter exceeded the bounded command duration")
            applied = True
        finally:
            self.last_receipt = PrimitiveReceipt(
                "applied" if applied else "failed", admission, command, result
            )
            snapshot = self._execution.world().snapshot(block["instance"])
            outcome = "command_applied" if applied else "command_failed"
            self._execution.complete(
                admission.block,
                admission.ticket_id,
                smsl.Event(outcome, time, snapshot.context),
            )
            self._pending.pop(admission.block)
            self._latest.pop(admission.block)
            self._times[block["instance"]] = time
            self._capture_id = self._latest_capture_id = None
        self.failed = False
        return self.last_receipt

    def halt(self):
        report = self._execution.halt()
        self._cancelling.update(
            (item["block"], item["ticket"]["id"]) for item in report["commands"]
        )
        return report

    def cancel_pending(self):
        """Acknowledge native cancellation; undispatched binary effects are inert."""
        self.halt()
        for block, ticket in tuple(self._cancelling):
            pending = self._pending.get(block)
            if pending is None or pending["ticket"]["id"] != ticket:
                raise ValueError("Cancellation must match the actual pending native ticket")
            self._execution.acknowledge_cancel(block, ticket)
            self._cancelling.remove((block, ticket))
            self._pending.pop(block)
            self._latest.pop(block, None)
        return self.inspect()

    def acknowledge_cancel(self, admission):
        if (
            not isinstance(admission, PrimitiveAdmission)
            or self._admissions.get(admission.admission_id) is not admission
            or (admission.block, admission.ticket_id) not in self._cancelling
        ):
            raise ValueError("Cancellation requires the exact native cancellation request")
        self._execution.acknowledge_cancel(admission.block, admission.ticket_id)
        self._cancelling.remove((admission.block, admission.ticket_id))
        self._pending.pop(admission.block)
        self._latest.pop(admission.block)
        self._spent.add(admission.admission_id)
        self.last_receipt = PrimitiveReceipt("cancelled", admission, None)
        return self.last_receipt

    def inspect(self):
        return self._execution.inspect()

    def facts(self, instance, branch):
        return self._execution.world().snapshot(instance).facts(branch)

    def context(self, instance):
        return self._execution.world().snapshot(instance).context
