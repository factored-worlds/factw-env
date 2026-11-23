"""Measure objective truth from native evidence independently of provider claims."""

from copy import deepcopy

from .information.evaluation_view import OBJECTIVE_CRITERIA, validate_evaluation_view


def evaluate(view):
    validate_evaluation_view(view)
    criteria = OBJECTIVE_CRITERIA[view["scenario"]]
    evidence = deepcopy(view["evidence"])
    tics = view["episode_tics"]
    known = tics is not None and all(value is not None for value in evidence.values())
    checks = {
        "equals": lambda value, target: value == target,
        "at-least": lambda value, target: value >= target,
        "greater-than": lambda value, target: value > target,
    }
    return {
        "schema": "doom.native-objective/1",
        "success": all(
            checks[operation](evidence[key], target)
            for key, (operation, target) in criteria.items()
        )
        if known
        else None,
        "authority": "reference-native-telemetry",
        "episode_tics": tics,
        "evidence": evidence,
        "criteria": {key: list(rule) for key, rule in criteria.items()},
        "terminated": view["terminated"],
        "truncated": view["truncated"],
        "continuation": "fresh-environment-replay-only",
    }
