from dataclasses import dataclass

import smsl
from factw.env.external.state_language import StateLanguageSession
from factw.env.worlds.doom.assets import document_sources

from ...information.access_policy import InformationBoundary
from ...information.player_observation import player_observation
from ...information.privileged_state import BASIC
from ...information.privileged_state.basic_telemetry import Telemetry

COMMANDS = {
    "left": {"buttons": {"MOVE_LEFT": 1}},
    "right": {"buttons": {"MOVE_RIGHT": 1}},
    "shoot": {"buttons": {"ATTACK": 1}},
    "wait": {"buttons": {}},
}


@dataclass(frozen=True)
class Decision:
    action: str
    basis: dict


class DoomSession:
    """Ground Basic telemetry and admit bounded commands using State Language."""

    def __init__(self, environment, *, information_profile="reference-assisted"):
        self.boundary = InformationBoundary(BASIC, profile=information_profile)
        if (
            environment.metadata.get("backend") != "vizdoom"
            or environment.metadata.get("configuration", {}).get("scenario") != "basic"
        ):
            raise ValueError("DoomSession requires the bundled ViZDoom Basic scenario")
        self.environment = environment
        self.execution = StateLanguageSession(environment)
        self.definition = smsl.loads(
            document_sources("games.doom/eliminate-single-target")["task.smsl"]
        )
        self.context = smsl.Context("doom", "basic", "telemetry")
        self.world = None
        self.telemetry = None
        self._ready = False

    def reset(self, *, seed=0):
        self._ready = False
        self.boundary.clear()
        self.world = None
        self.telemetry = None
        observation = self.execution.reset(seed=seed)
        self.world = smsl.World()
        self.world.spawn("doom", self.definition, self.context)
        self._observe(observation)
        self._ready = True
        return observation

    def _observe(self, observation):
        from factw.env.core.core import AgentObservation

        self.boundary.capture(
            observation,
            terminated=self.environment.terminated,
            truncated=self.environment.truncated,
        )
        projected = self.boundary.reference_inputs()
        current = Telemetry.read(AgentObservation(structured=projected["structured"]))
        if self.telemetry is not None and current.tics <= self.telemetry.tics:
            raise ValueError("Doom grounding requires fresh observed simulation tics")
        self.world.advance(
            "doom",
            smsl.Event(
                "observed",
                current.tics,
                self.context,
                payload={
                    "active": not (self.environment.terminated or self.environment.truncated),
                    "alive": current.health > 0,
                    "ammo": current.ammo > 0,
                    "won": current.kills >= 1,
                },
            ),
        )
        self.telemetry = current
        self.observation = observation

    def player_view(self):
        if not self._ready:
            raise RuntimeError("Reset before reading the Doom player view")
        return player_observation(self.observation, capture_id=self.boundary.capture_id)

    def facts(self):
        if self.world is None:
            raise RuntimeError("Reset before inspecting Doom facts")
        return self.world.snapshot("doom").facts("Task")

    def policy_inputs(self):
        if not self._ready:
            raise RuntimeError("Reset before reading the Doom policy input")
        return self.boundary.basic_policy_inputs(
            facts=self.facts(), position_y=self.telemetry.position_y, basis=self.execution.basis
        )

    def propose_policy_action(self, action, provenance):
        if not self._ready:
            raise RuntimeError("Reset before planning an inactive Doom session")
        if provenance != {
            "capture_id": self.boundary.capture_id,
            "access_sha256": self.boundary.digest,
            "basis": self.execution.basis,
        }:
            raise ValueError("Doom policy provenance is stale or invalid")
        return self.propose(action)

    def propose(self, action):
        if not self._ready:
            raise RuntimeError("Reset before planning an inactive Doom session")
        if action not in COMMANDS:
            raise ValueError("Unknown Doom Basic action")
        if not self.world.action_applicable("doom", "Task", action, {}):
            raise ValueError(f"Doom action {action} is not applicable to observed facts")
        return Decision(action, self.execution.basis)

    def step(self, decision):
        admitted = self.propose(decision.action)
        if decision.basis != admitted.basis:
            raise ValueError("Doom decision basis is stale")
        self._ready = False
        result = self.execution.step(COMMANDS[decision.action], basis=decision.basis)
        self._observe(result.observation)
        self._ready = True
        return result

    def close(self):
        self._ready = False
        self.boundary.clear()
        self.execution.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
