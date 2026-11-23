"""Declared telemetry and visible native labels for the assisted combat mission."""

from copy import deepcopy
from math import isfinite

VARIABLES = (
    "POSITION_X",
    "POSITION_Y",
    "ANGLE",
    "HEALTH",
    "AMMO2",
    "ARMOR",
    "KILLCOUNT",
    *(f"USER{index}" for index in range(1, 14)),
)
SCENE_FIELDS = (
    "health",
    "ammo",
    "armor",
    "supply_approach",
    "arena_entry",
    "key",
    "door_approach",
    "door_crossing",
    "reactor",
    "reserve_health",
    "extraction_approach",
    "extraction_crossing",
    "exit",
    "door_direction",
    "reactor_direction",
    "required_kills",
    "regions",
)
FLAGS = {
    "has_key": "USER1",
    "door_open": "USER2",
    "at_exit": "USER3",
    "reactor_active": "USER4",
    "near_door": "USER6",
    "near_reactor": "USER7",
    "health_available": "USER8",
    "ammo_available": "USER9",
    "reserve_health_available": "USER10",
    "extraction_open": "USER11",
    "armor_available": "USER12",
}
BOOLEANS = (
    "active",
    "alive",
    "health_low",
    "ammo_low",
    "has_ammo",
    "armored",
    "threat",
    "fireball_visible",
    "incoming_fireball",
    "threats_clear",
    *FLAGS,
)
REGIONS = {1: "supply", 2: "arena", 3: "reactor", 4: "extraction"}
FACT_COUNTS = {"visible_fireball_count": 4294967295}
FACT_ENUMS = {
    "region": tuple(REGIONS.values()),
    "fireball_pass_side": ("none", "left", "right", "center"),
}


def finite(value):
    return type(value) in (float, int) and isfinite(value)


def validate_facts(value):
    if (
        type(value) is not dict
        or set(value) != {*BOOLEANS, *FACT_ENUMS, *FACT_COUNTS}
        or type(value["active"]) is not bool
    ):
        raise ValueError("Invalid combat fact payload")
    if any(value[key] is not None and type(value[key]) is not bool for key in BOOLEANS):
        raise ValueError("Combat facts must be true, false or unknown")
    for key, allowed in FACT_ENUMS.items():
        if value[key] is not None and value[key] not in allowed:
            raise ValueError(f"Invalid combat fact: {key}")
    for key, maximum in FACT_COUNTS.items():
        item = value[key]
        if item is not None and (type(item) is not int or not 0 <= item <= maximum):
            raise ValueError(f"Invalid combat count: {key}")


def scene_spec(value):
    if type(value) is not dict or set(value) != set(SCENE_FIELDS):
        raise ValueError("Scene topology must match the combat-mission payload profile")
    if value["required_kills"] != 2 or value["regions"] != {
        name: index for index, name in REGIONS.items()
    }:
        raise ValueError("Combat mission requires its declared enemy count and region identities")
    for key, item in value.items():
        if key in ("required_kills", "regions"):
            continue
        numbers = [item] if key.endswith("_direction") else item
        size = 1 if key.endswith("_direction") else 2
        if type(numbers) is not list or len(numbers) != size or not all(map(finite, numbers)):
            raise ValueError("Combat topology requires finite coordinate pairs and directions")
    return deepcopy(value)


def progress(updates):
    return {
        key: updates[key]
        for key in ("active", "has_key", "door_open", "reactor_active", "threats_clear", "at_exit")
    }
