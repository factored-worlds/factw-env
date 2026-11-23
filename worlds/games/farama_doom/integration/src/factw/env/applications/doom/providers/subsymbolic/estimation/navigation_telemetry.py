"""Validate native navigation pose, health and mission telemetry."""

from math import isfinite

from ....contracts.navigation import VARIABLES


def estimate(observation):
    if not isinstance(observation, dict) or set(observation) != {"structured", "active"}:
        raise ValueError("Expected structured telemetry and active episode status")
    data = observation["structured"]
    tics = data.get("episode_tics")
    if type(tics) is not int or tics < 0 or type(observation["active"]) is not bool:
        raise ValueError("Telemetry requires nonnegative tics and Boolean active status")
    values = data.get("game_variables", {})
    if not isinstance(values, dict):
        raise ValueError("game_variables must be an object")
    measurements = {}
    for name in VARIABLES:
        value = values.get(name)
        if value is not None and (type(value) not in (float, int) or not isfinite(value)):
            raise ValueError(f"Invalid finite telemetry: {name}")
        measurements[name] = value
    for name in ("USER1", "USER2", "USER3", "USER4"):
        if measurements[name] is not None and measurements[name] not in (0, 1):
            raise ValueError(f"Invalid binary task telemetry: {name}")
    if measurements["USER5"] is not None and measurements["USER5"] not in (1, 2):
        raise ValueError("Region telemetry must be 1, 2 or unavailable")
    return {"tics": tics, "active": observation["active"], "measurements": measurements}
