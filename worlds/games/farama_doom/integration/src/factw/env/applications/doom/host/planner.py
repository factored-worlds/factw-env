"""Explicit replacement of one pure, domain-compatible planner binding."""

from dataclasses import dataclass
from importlib import import_module
from inspect import signature

from ..information.privileged_state import COMBAT, NAVIGATION


@dataclass(frozen=True)
class PlannerBinding:
    provider_id: str
    scenario: str
    function: object

    def validate(self, scenario):
        if self.scenario != scenario or scenario not in (COMBAT, NAVIGATION):
            raise ValueError("Planner binding does not match the Doom scenario payload")
        if type(self.provider_id) is not str or not self.provider_id or not callable(self.function):
            raise ValueError("Planner binding requires an implementation ID and callable")
        signature(self.function).bind(knowledge={}, goal={})
        return self

    def describe(self):
        return {
            "id": self.provider_id,
            "contract": "symbolic.plan",
            "scenario": self.scenario,
            "implementation": f"{self.function.__module__}:{self.function.__name__}",
            "effect": "pure",
            "inputs": ["knowledge", "goal"],
            "output_profile": "doom.combat.plan.v1" if self.scenario == COMBAT else "doom.plan.v1",
            "assistance": "reference-assisted",
        }


def load_planner(target, scenario):
    module, separator, name = target.partition(":")
    if not separator or not module or not name:
        raise ValueError("Planner selection must be module:factory")
    binding = getattr(import_module(module), name)()
    if not isinstance(binding, PlannerBinding):
        raise ValueError("Planner factory must return PlannerBinding")
    return binding.validate(scenario)
