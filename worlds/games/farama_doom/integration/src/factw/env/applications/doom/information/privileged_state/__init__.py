"""Allowlisted native reference views and their derived numeric estimates."""

from copy import deepcopy
from math import isfinite

from ...contracts import combat, navigation

BASIC = "games.doom/eliminate-single-target"
NAVIGATION = "games.doom/retrieve-key-and-escape"
COMBAT = "games.doom/activate-reactor-and-extract"
BASIC_VARIABLES = ("POSITION_Y", "AMMO2", "HEALTH", "KILLCOUNT")
LABEL_FIELDS = ("id", "name", "category", "position")
REFERENCE_VARIABLES = {
    BASIC: BASIC_VARIABLES,
    NAVIGATION: navigation.VARIABLES,
    COMBAT: combat.VARIABLES,
}


def reference_view(observation, *, scenario, active):
    data = observation.structured
    native = data.get("game_variables", {})
    if type(native) is not dict:
        raise ValueError("Doom reference telemetry requires game_variables")
    structured = {
        "episode_tics": data.get("episode_tics"),
        "game_variables": {name: native.get(name) for name in REFERENCE_VARIABLES[scenario]},
    }
    if scenario == COMBAT:
        labels = data.get("labels")
        if labels is not None and type(labels) is not list:
            raise ValueError("Doom reference labels require an array or null")
        if labels is not None and any(type(item) is not dict for item in labels):
            raise ValueError("Doom reference labels require object entries")
        structured["labels"] = (
            None
            if labels is None
            else [{key: deepcopy(item.get(key)) for key in LABEL_FIELDS} for item in labels]
        )
    result = {"structured": structured, "active": active}
    validate_reference(result, scenario=scenario)
    return result


def validate_reference(value, *, scenario):
    fields = {"episode_tics", "game_variables"}
    if scenario == COMBAT:
        fields.add("labels")
    if (
        type(value) is not dict
        or set(value) != {"structured", "active"}
        or type(value["structured"]) is not dict
        or set(value["structured"]) != fields
        or type(value["structured"]["game_variables"]) is not dict
        or set(value["structured"]["game_variables"]) != set(REFERENCE_VARIABLES[scenario])
    ):
        raise ValueError("Doom provider reference view has undeclared fields")
    estimate = {
        "tics": value["structured"]["episode_tics"],
        "active": value["active"],
        "measurements": value["structured"]["game_variables"],
    }
    if scenario == COMBAT:
        estimate["labels"] = value["structured"]["labels"]
    validate_estimate(estimate, scenario=scenario)
    return value


def validate_estimate(value, *, scenario):
    fields = {"tics", "active", "measurements"}
    if scenario == COMBAT:
        fields.add("labels")
    if (
        type(value) is not dict
        or set(value) != fields
        or type(value["measurements"]) is not dict
        or set(value["measurements"]) != set(REFERENCE_VARIABLES[scenario])
    ):
        raise ValueError("Doom estimate has undeclared fields")
    if type(value["tics"]) is not int or value["tics"] < 0 or type(value["active"]) is not bool:
        raise ValueError(
            "Doom estimate requires nonnegative episode tics and Boolean active status"
        )
    measurements = value["measurements"]
    if any(
        item is not None and (type(item) not in (int, float) or not isfinite(item))
        for item in measurements.values()
    ):
        raise ValueError("Doom measurements require finite numbers or null")
    flags = combat.FLAGS.values() if scenario == COMBAT else ("USER1", "USER2", "USER3", "USER4")
    if scenario != BASIC and any(measurements[name] not in (None, 0, 1) for name in flags):
        raise ValueError("Doom task signals require binary values or null")
    if scenario == NAVIGATION and measurements["USER5"] not in (None, 1, 2):
        raise ValueError("Doom navigation region must be 1, 2 or null")
    if scenario == COMBAT and measurements["USER13"] not in (None, *combat.REGIONS):
        raise ValueError("Doom combat region is unknown")
    counts = (
        ("AMMO2", "ARMOR", "KILLCOUNT", "USER5")
        if scenario == COMBAT
        else ("AMMO2", "KILLCOUNT")
        if scenario == BASIC
        else ()
    )
    if any(
        measurements[name] is not None
        and (measurements[name] < 0 or measurements[name] != int(measurements[name]))
        for name in counts
    ):
        raise ValueError("Doom counts require nonnegative integers or null")
    if scenario == COMBAT and value["labels"] is not None:
        if type(value["labels"]) is not list:
            raise ValueError("Doom labels require an array or null")
        if any(
            type(label) is not dict or set(label) != set(LABEL_FIELDS) for label in value["labels"]
        ):
            raise ValueError("Doom estimate has undeclared label fields")
        for label in value["labels"]:
            if (
                type(label["id"]) is not int
                or type(label["name"]) is not str
                or type(label["category"]) is not str
                or type(label["position"]) is not list
                or len(label["position"]) != 3
                or not all(combat.finite(item) for item in label["position"])
            ):
                raise ValueError("Doom label requires an ID, name, category and finite 3D position")
