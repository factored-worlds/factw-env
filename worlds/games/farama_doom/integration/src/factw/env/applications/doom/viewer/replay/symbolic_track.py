"""Replay native Doom measurements through the installed State Language models."""

import hashlib
from importlib.metadata import version

import smsl
from factw.env.applications.doom.contracts import combat, navigation
from factw.env.applications.doom.providers.subsymbolic.estimation import (
    combat_telemetry_and_labels as combat_estimate,
)
from factw.env.applications.doom.providers.subsymbolic.estimation import (
    navigation_telemetry as navigation_estimate,
)
from factw.env.applications.doom.providers.symbolic.grounding import (
    combat_telemetry_and_labels as combat_grounding,
)
from factw.env.applications.doom.providers.symbolic.grounding import (
    navigation_telemetry as navigation_grounding,
)
from factw.env.applications.doom.providers.symbolic.grounding.fireball_facts import FireballFacts
from factw.env.worlds.doom.assets import document_bytes, scenario_identity

SCENARIOS = {
    "games.doom/retrieve-key-and-escape": (navigation, navigation_estimate, navigation_grounding),
    "games.doom/activate-reactor-and-extract": (combat, combat_estimate, combat_grounding),
}
MODELS = {"Scene": "domain.smsl", "Task": "task.smsl"}


def facts(world):
    return {
        f"{branch}.{name}": None if value is smsl.UNKNOWN else value
        for branch in MODELS
        for name, value in world.snapshot(branch).facts(branch).items()
    }


def observe(world, branch, event, tic, payload, source):
    transition = world.advance(
        branch, smsl.Event(event, tic, world.snapshot(branch).context, payload=payload)
    )
    ref = transition.event_ref
    return {
        "branch": branch,
        "event": event,
        "payload": payload,
        "ref": {"scope": ref.scope, "step": ref.step},
        "source": source,
    }


class ObservationTrack:
    """Ground chronologically ordered native observations in the installed SMSL models."""

    def __init__(self, scenario, identity, *, source="replay"):
        if scenario not in SCENARIOS:
            raise ValueError(f"No recorded-data projection for Doom scenario {scenario!r}")
        self._contract, self._estimator, self._grounding = SCENARIOS[scenario]
        self._ground = (
            combat_grounding.make_grounder()
            if self._contract is combat
            else navigation_grounding.ground
        )
        sources = document_bytes(scenario)
        self.world = smsl.World()
        for branch, model in MODELS.items():
            context = smsl.Context(f"doom-{source}/{identity}/{branch}", identity, "tics")
            self.world.spawn(branch, smsl.loads(sources[model].decode("utf-8")), context)
        self.model = {
            **scenario_identity(scenario),
            **{
                branch.lower(): {
                    "filename": model,
                    "sha256": hashlib.sha256(sources[model]).hexdigest(),
                }
                for branch, model in MODELS.items()
            },
        }
        self._fireball_facts = None
        if self._contract is combat:
            name = "fireball.smsl"
            self._fireball_facts = FireballFacts(
                self.world,
                sources[name],
                scope=f"doom-{source}/{identity}/visible-fireballs",
                clock="tics",
            )
            self.model["fireball"] = {
                "filename": name,
                "sha256": hashlib.sha256(sources[name]).hexdigest(),
            }
        self.grounding = {
            "estimator": self._estimator.__name__,
            "projection": self._grounding.__name__,
        }
        self._current_facts = facts(self.world)
        self._previous_updates = {}
        self._previous_progress = None
        self._previous_tic = -1

    def observe(self, row):
        tic = row["tic"]
        if type(tic) is not int or tic <= self._previous_tic or type(row["terminal"]) is not bool:
            raise ValueError("Doom observations require increasing integer tics and terminal flags")
        native = {
            "episode_tics": tic,
            "game_variables": row["variables"],
            "labels": row.get("labels"),
        }
        estimate = self._estimator.estimate({"structured": native, "active": not row["terminal"]})
        updates = self._ground(estimate)
        self._contract.validate_facts(updates)
        observations = [
            observe(
                self.world, "Scene", f"observed_{key}", tic, {"value": value}, "native_grounding"
            )
            for key, value in updates.items()
            if key not in self._previous_updates or self._previous_updates[key] != value
        ]
        progress = self._contract.progress(updates)
        if progress != self._previous_progress:
            observations.append(
                observe(self.world, "Task", "progress", tic, progress, "grounded_scene")
            )

        before = self._current_facts
        if observations:
            self._current_facts = facts(self.world)
        changes = {
            key: {"before": before[key], "after": value}
            for key, value in self._current_facts.items()
            if before[key] != value
        }
        self._previous_updates = updates
        self._previous_progress = progress
        self._previous_tic = tic
        projected = {
            **row,
            "facts": self._current_facts,
            "changes": changes,
            "observations": observations,
        }
        if self._fireball_facts is not None:
            observations.extend(self._fireball_facts.observe(estimate, tick=tic))
            projected["fireballs"] = self._fireball_facts.facts()
        return projected


def compile_track(capture):
    if capture["schema"] != "factw.doom.human-captures/1":
        raise ValueError("Unknown Doom replay capture format")
    if not capture["frames"] or capture["frames"][0]["tic"] != 0:
        raise ValueError("Replay captures must start at relative tic zero")

    track = ObservationTrack(capture["scenario"], capture["demo_sha256"])
    result = {
        **capture,
        "schema": "factw.doom.human-symbolic/1",
        "frames": [track.observe(row) for row in capture["frames"]],
        "model": track.model,
        "runtime": {
            name: version(name)
            for name in ("pysmsl", "factored-worlds-doom", "factored-worlds-doom-application")
        },
        "grounding": track.grounding,
    }
    return result, track.world
