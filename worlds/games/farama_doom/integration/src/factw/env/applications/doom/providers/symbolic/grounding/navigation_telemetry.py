"""Ground navigation facts from native health and mission telemetry."""


def ground(value):
    measurements = value["measurements"]

    def flag(name):
        return None if measurements[name] is None else bool(measurements[name])

    health, region = measurements["HEALTH"], measurements["USER5"]
    return {
        "active": value["active"],
        "alive": None if health is None else health > 0,
        "has_key": flag("USER1"),
        "door_open": flag("USER2"),
        "at_exit": flag("USER3"),
        "near_door": flag("USER4"),
        "region": None if region is None else "key_room" if region == 1 else "exit_room",
    }
