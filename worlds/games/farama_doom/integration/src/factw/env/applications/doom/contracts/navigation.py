"""Explicit telemetry assistance; unavailable measurements remain unknown."""

from math import isfinite

VARIABLES = (
    "POSITION_X",
    "POSITION_Y",
    "ANGLE",
    "HEALTH",
    "USER1",
    "USER2",
    "USER3",
    "USER4",
    "USER5",
)
FACTS = ("alive", "has_key", "door_open", "near_door", "at_exit", "region")
SCENE_FIELDS = ("key_position", "door_approach", "door_crossing", "exit_position", "door_direction")


def validate_facts(value):
    if (
        type(value) is not dict
        or set(value) != {"active", *FACTS}
        or type(value["active"]) is not bool
    ):
        raise ValueError("Invalid grounded fact payload")
    if any(value[key] is not None and type(value[key]) is not bool for key in FACTS[:-1]):
        raise ValueError("Grounded Boolean facts must be true, false or unknown")
    if value["region"] not in (None, "key_room", "exit_room"):
        raise ValueError("Invalid grounded region")


def scene_spec(value):
    if type(value) is not dict or set(value) != set(SCENE_FIELDS):
        raise ValueError("Scene topology must match the key-door-exit payload profile")
    for key, item in value.items():
        numbers = [item] if key == "door_direction" else item
        if type(numbers) is not list or len(numbers) != (1 if key == "door_direction" else 2):
            raise ValueError("Scene topology positions require two coordinates")
        if any(type(number) not in (int, float) or not isfinite(number) for number in numbers):
            raise ValueError("Scene topology coordinates must be finite")
    return {key: item.copy() if isinstance(item, list) else item for key, item in value.items()}


def progress(updates):
    return {key: updates[key] for key in ("has_key", "door_open", "at_exit", "alive", "active")}
