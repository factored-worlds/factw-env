"""Closed native objective evidence, separate from provider inputs and claims."""

from math import isfinite

from .privileged_state import BASIC, COMBAT, NAVIGATION

OBJECTIVE_CRITERIA = {
    BASIC: {"KILLCOUNT": ("at-least", 1)},
    NAVIGATION: {key: ("equals", 1) for key in ("USER1", "USER2", "USER3")},
    COMBAT: {
        **{key: ("equals", 1) for key in ("USER1", "USER2", "USER3", "USER4", "USER11")},
        "USER5": ("equals", 0),
        "HEALTH": ("greater-than", 0),
    },
}


def evaluation_view(observation, *, scenario, capture_id, terminated, truncated):
    if type(scenario) is not str or scenario not in OBJECTIVE_CRITERIA:
        raise ValueError("Unknown Doom objective scenario")
    data = observation.structured
    if type(data) is not dict or type(data.get("game_variables", {})) is not dict:
        raise ValueError("Doom evaluation requires native structured game variables")
    native = data.get("game_variables", {})
    view = {
        "scenario": scenario,
        "capture_id": capture_id,
        "episode_tics": data.get("episode_tics"),
        "evidence": {key: native.get(key) for key in OBJECTIVE_CRITERIA[scenario]},
        "terminated": terminated,
        "truncated": truncated,
    }
    return validate_evaluation_view(view)


def validate_evaluation_view(view):
    if (
        type(view) is not dict
        or set(view)
        != {"scenario", "capture_id", "episode_tics", "evidence", "terminated", "truncated"}
        or type(view["scenario"]) is not str
        or view["scenario"] not in OBJECTIVE_CRITERIA
        or type(view["evidence"]) is not dict
        or set(view["evidence"]) != set(OBJECTIVE_CRITERIA[view["scenario"]])
    ):
        raise ValueError("Doom evaluation view has undeclared fields")
    if type(view["capture_id"]) is not str or not view["capture_id"]:
        raise ValueError("Doom evaluation requires capture provenance")
    tics = view["episode_tics"]
    if tics is not None and (type(tics) is not int or tics < 0):
        raise ValueError("Doom evaluation requires nonnegative episode tics or null")
    if any(
        value is not None and (type(value) not in (int, float) or not isfinite(value))
        for value in view["evidence"].values()
    ):
        raise ValueError("Doom objective evidence requires finite numbers or null")
    if type(view["terminated"]) is not bool or type(view["truncated"]) is not bool:
        raise ValueError("Doom evaluation requires Boolean boundary flags")
    return view
