"""Validate native combat pose, mission telemetry and object labels."""

from ....contracts.combat import FLAGS, REGIONS, VARIABLES, finite


def estimate(observation):
    if not isinstance(observation, dict) or set(observation) != {"structured", "active"}:
        raise ValueError("Expected structured telemetry and active episode status")
    data = observation["structured"]
    tics = data.get("episode_tics")
    if type(tics) is not int or tics < 0 or type(observation["active"]) is not bool:
        raise ValueError("Telemetry requires nonnegative tics and Boolean active status")
    native = data.get("game_variables", {})
    if not isinstance(native, dict):
        raise ValueError("game_variables must be an object")
    measurements = {name: native.get(name) for name in VARIABLES}
    for name, value in measurements.items():
        if value is not None and not finite(value):
            raise ValueError(f"Invalid finite telemetry: {name}")
    for name in FLAGS.values():
        if measurements[name] is not None and measurements[name] not in (0, 1):
            raise ValueError(f"Invalid binary task telemetry: {name}")
    if measurements["USER13"] is not None and measurements["USER13"] not in REGIONS:
        raise ValueError("Unknown mission region")
    for name in ("AMMO2", "ARMOR", "KILLCOUNT", "USER5"):
        value = measurements[name]
        if value is not None and (value < 0 or value != int(value)):
            raise ValueError(f"Expected nonnegative native count: {name}")
    labels = data.get("labels")
    if labels is not None:
        if type(labels) is not list:
            raise ValueError("Visible labels must be an array or unavailable")
        for label in labels:
            if type(label) is not dict or type(label.get("category")) is not str:
                raise ValueError("A native visible label requires its category")
            position = label.get("position")
            if type(position) is not list or len(position) != 3 or not all(map(finite, position)):
                raise ValueError("A native visible label requires a finite 3D position")
            if type(label.get("id")) is not int or type(label.get("name")) is not str:
                raise ValueError("A native visible label requires its identifier and name")
    return {
        "tics": tics,
        "active": observation["active"],
        "measurements": measurements,
        "labels": labels,
    }
