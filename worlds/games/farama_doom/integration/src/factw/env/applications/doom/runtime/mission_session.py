"""Schedule observed planning and one bounded control segment at a time."""

from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

import smsl
from factw.env.worlds.doom.assets import default_scene_spec

from ..information.access_policy import InformationBoundary
from ..information.player_observation import player_observation
from .invocation import Runtime


@dataclass(frozen=True)
class Decision:
    action: str
    basis: dict
    sequence: int


@dataclass(frozen=True)
class NavigationStep:
    command: dict
    result: object
    trace: dict


class MissionSession:
    def __init__(
        self,
        environment,
        mission,
        scene_spec=None,
        *,
        max_skill_steps=80,
        stuck_steps=12,
        planner=None,
        information_profile="reference-assisted",
        apply_command=None,
    ):
        self.mission = mission
        self.boundary = InformationBoundary(mission.scenario, profile=information_profile)
        self.planner = None if planner is None else planner.validate(mission.scenario)
        schema = mission.schema
        config = environment.metadata.get("configuration", {})
        if (
            environment.metadata.get("backend") != "vizdoom"
            or Path(config.get("config_path", "")).name != mission.config_name
        ):
            raise ValueError(f"Mission requires the {mission.config_name} scenario")
        for value in (max_skill_steps, stuck_steps):
            if type(value) is not int or value < 1:
                raise ValueError("Skill and stuck budgets must be positive integers")
        self.environment = environment
        self._apply_command = self._apply_lockstep if apply_command is None else apply_command
        self.topology = schema.scene_spec(
            default_scene_spec(mission.scenario) if scene_spec is None else scene_spec
        )
        self.max_skill_steps, self.stuck_steps = max_skill_steps, stuck_steps
        self.application = mission.definition(planner=self.planner)
        self._world = None
        self.runtime = None
        self.world = None
        self.active_skill = None
        self._ready = False
        self._clear()

    def _clear(self):
        self.estimate = self.observation = self.updates = None
        self.plan = self.last_outcome = self.stop_reason = None
        self.last_command = None
        self.trace = []
        self._event_time = 0
        self._trace_cursor = 0

    def reset(self, *, seed=0):
        self.close()
        self.world = None
        self._clear()
        self.application = self.mission.definition(scope=uuid4().hex, planner=self.planner)
        self._world = smsl.create_application_world(self.application)
        self.runtime = Runtime(
            self.application,
            self._world,
            self.mission.providers,
            planner=self.planner,
            boundary=self.boundary,
        )
        observation = self.environment.reset(seed=seed)
        self._observe(observation)
        self.world = self._world
        self._ready = True
        self._trace_cursor = len(self.runtime.calls)
        return observation

    def _require_ready(self):
        if not self._ready or self.runtime is None or self.runtime.failed:
            raise RuntimeError("Reset before using an inactive or failed navigation session")

    @property
    def basis(self):
        self._require_ready()
        return self.runtime.bridge.basis()

    def facts(self):
        self._require_ready()
        return {
            key: {
                name: None if value is smsl.UNKNOWN else value
                for name, value in self._world.snapshot(key).facts(branch).items()
            }
            for key, branch in (("scene", "Scene"), ("task", "Task"))
        }

    @property
    def success(self):
        return (
            self._ready
            and not self.runtime.failed
            and self.mission.policy.success(self.updates, self.facts())
        )

    def _observe(self, observation):
        self.boundary.capture(
            observation,
            terminated=self.environment.terminated,
            truncated=self.environment.truncated,
        )
        value = self.runtime.invoke(
            "perception.estimate",
            {"observation": self.boundary.reference_inputs()},
        )["estimate"]
        if self.estimate is not None and value["tics"] <= self.estimate["tics"]:
            raise ValueError("Navigation grounding requires fresh simulation evidence")
        updates = self.runtime.invoke("grounding.facts")["updates"]
        self._event_time += 1
        events = [
            ("scene", "observed_" + key, {"value": value})
            for key, value in updates.items()
            if key == "active" or self.updates is None or self.updates[key] != value
        ]
        progress = self.mission.schema.progress(updates)
        if self.updates is None or progress != self.mission.schema.progress(self.updates):
            events.append(("task", "progress", progress))
        for instance, event, payload in events:
            self._world.advance(
                instance,
                smsl.Event(
                    event, self._event_time, self._world.snapshot(instance).context, payload=payload
                ),
            )
            if instance == "scene":
                self.runtime.advance()
        self.estimate, self.updates, self.observation = value, updates, observation

    def player_view(self):
        self._require_ready()
        return player_observation(self.observation, capture_id=self.boundary.capture_id)

    def propose(self):
        self._require_ready()
        if self.active_skill is not None:
            raise RuntimeError("Finish or cancel the active skill before planning")
        self.plan = self.runtime.invoke("planner.plan")["plan"]
        if self.plan["status"] == "blocked":
            self.stop_reason = self.plan["reason"]
            return None
        return Decision(self.plan["action"], self.basis, self.runtime.sequence)

    def start(self, decision):
        self._require_ready()
        if self.active_skill is not None:
            raise RuntimeError("Finish or cancel the active skill before starting another")
        if decision.basis != self.basis or decision.sequence != self.runtime.sequence:
            raise ValueError("Navigation decision basis or sequence is stale")
        if self.plan is None or decision.action != self.plan.get("action"):
            raise ValueError("Navigation decision differs from the current validated proposal")
        ticket = self.runtime.bridge.begin_action(
            "Scene", decision.action, {}, basis=decision.basis
        )
        self.active_skill = {
            "action": decision.action,
            "ticket": ticket,
            "started_tics": self.estimate["tics"],
            "steps": 0,
            "stuck": 0,
            "baseline": self.mission.policy.baseline(self.estimate),
        }
        self.runtime.invoke(
            "dispatcher.execute",
            {
                "invocation": {
                    "operation": "start",
                    "ticket": ticket.id,
                    "skill": decision.action,
                    "baseline": self.active_skill["baseline"],
                }
            },
            effects=True,
        )
        self.stop_reason = None
        return self._skill_description()

    def _skill_description(self):
        if self.active_skill is None:
            return None
        return {
            **{key: value for key, value in self.active_skill.items() if key != "ticket"},
            "ticket": self.active_skill["ticket"].id,
        }

    def _finish(self, status, reason):
        skill = self.active_skill
        self.last_outcome = self.runtime.invoke(
            "dispatcher.execute",
            {
                "invocation": {
                    "operation": "finish",
                    "ticket": skill["ticket"].id,
                    "started_tics": skill["started_tics"],
                    "status": status,
                    "reason": reason,
                },
                "feedback": {
                    "tics": self.estimate["tics"],
                    "facts": self.updates,
                    "estimate": self.estimate,
                },
            },
            effects=True,
        )["outcome"]
        self._event_time += 1
        self.runtime.bridge.complete_action(
            skill["ticket"],
            smsl.Event(
                "skill_finished",
                self._event_time,
                self.runtime.bridge.snapshot().context,
                payload={"skill": skill["action"], "status": status},
            ),
        )
        self.active_skill = None
        self.runtime.advance()
        if status == "failed":
            self.stop_reason = reason

    def step(self):
        self._require_ready()
        if self.active_skill is None:
            raise RuntimeError("Start an admitted skill before requesting a control step")
        before, skill = self.estimate, self.active_skill
        before_facts, before_basis = self.facts(), self.basis
        trace_start = self._trace_cursor
        self._ready = False
        self.runtime.invoke(
            "dispatcher.refine",
            {
                "action": {"branch": "Scene", "action": skill["action"]},
                "condition": self.mission.policy.condition(self.topology, skill),
            },
        )
        command = self.runtime.invoke("actor.control", {"estimate": before}, effects=True)[
            "command"
        ]
        if self.runtime.bridge.basis() != before_basis:
            raise ValueError("Navigation control basis changed before dispatch")
        command, result, pacing = self._apply_command(command)
        self.last_command = command
        self._observe(result.observation)
        self._ready = True
        skill["steps"] += 1
        moved = self.mission.policy.displacement(before, self.estimate)
        if "MOVE_FORWARD" in command["buttons"]:
            skill["stuck"] = skill["stuck"] + 1 if moved is not None and moved < 0.25 else 0
        if self.mission.policy.confirmed(
            skill["action"], self.updates, skill["baseline"], self.estimate
        ):
            self._finish("succeeded", "observed_postcondition")
        elif self.updates["alive"] is False:
            self._finish("failed", "dead")
        elif result.truncated:
            self.cancel_active("episode_truncated")
        elif result.terminated:
            self._finish("failed", "episode_ended")
        elif self.mission.policy.lost_evidence(skill["action"], self.updates, self.estimate):
            self._finish("failed", "lost_evidence")
        elif skill["stuck"] >= self.stuck_steps:
            self._finish("failed", "stuck")
        elif skill["steps"] >= self.max_skill_steps:
            self._finish("failed", "skill_timeout")
        entry = {
            "skill": skill["action"],
            "ticket": skill["ticket"].id,
            "basis": before_basis,
            "episode_tics": self.estimate["tics"],
            "facts_before": before_facts,
            "facts_after": self.facts(),
            "command": command,
            "last_outcome": self.last_outcome,
            "calls": self.runtime.calls[trace_start:],
        }
        if pacing is not None:
            entry["pacing"] = pacing
        entry["interruptions"] = [
            call["outputs"]["outcome"]
            for call in entry["calls"]
            if call["outputs"].get("outcome", {}).get("status") == "cancelled"
        ]
        self._trace_cursor = len(self.runtime.calls)
        self.trace.append(entry)
        return NavigationStep(command, result, entry)

    def _apply_lockstep(self, command):
        return command, self.environment.step(command), None

    def tick(self):
        self._require_ready()
        if self.stop_reason is not None:
            return None
        if self.environment.terminated or self.environment.truncated:
            self.stop_reason = "observed_exit" if self.success else "episode_boundary"
            return None
        if any(
            self.estimate["measurements"][key] is None
            for key in ("POSITION_X", "POSITION_Y", "ANGLE")
        ):
            self.cancel_active("lost_evidence")
            self.stop_reason = "lost_evidence"
            return None
        if self.active_skill is not None:
            reason = self.mission.policy.interruption(
                self.active_skill["action"], self.facts()["scene"]
            )
            if reason is not None:
                self.cancel_active(reason)
                self.stop_reason = None
        if self.active_skill is None:
            decision = self.propose()
            if decision is None:
                return None
            self.start(decision)
        return self.step()

    def cancel_active(self, reason="interrupted"):
        if self.active_skill is None:
            return None
        ticket = self.active_skill["ticket"]
        invocation = {"operation": "cancel", "ticket": ticket.id, "reason": reason}
        try:
            if self.runtime.failed:
                self.last_outcome = {
                    "ticket": ticket.id,
                    "skill": self.active_skill["action"],
                    "status": "cancelled",
                    "reason": reason,
                    "provider_failed": True,
                }
                self.runtime.dispatcher.active = None
            else:
                self.last_outcome = self.runtime.invoke(
                    "dispatcher.execute", {"invocation": invocation}, effects=True
                )["outcome"]
        finally:
            self.runtime.bridge.cancel_action(ticket, acknowledged=True)
            self.active_skill = None
            self.stop_reason = reason
        return self.last_outcome

    def inspect(self, *, history=True):
        inspection = {
            "facts": self.facts(),
            "basis": self.basis,
            "plan": self.plan,
            "skill": self._skill_description(),
            "stop_reason": self.stop_reason,
            "last_outcome": self.last_outcome,
            "episode_tics": self.estimate["tics"],
            "estimate": self.estimate,
            "continuation": "Symbolic archives do not restore the Doom simulator.",
            "information": self.boundary.describe(),
            "planner": None if self.planner is None else self.planner.describe(),
        }
        if history:
            inspection.update(
                providers=self.runtime.session.inspect(),
                application=self.application.inspect(),
                calls=self.runtime.calls,
            )
        return inspection

    def close(self):
        self._ready = False
        try:
            if self.runtime is not None:
                try:
                    self.cancel_active("closed")
                finally:
                    self.runtime.close()
                    self.runtime = None
        finally:
            self.boundary.clear()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
