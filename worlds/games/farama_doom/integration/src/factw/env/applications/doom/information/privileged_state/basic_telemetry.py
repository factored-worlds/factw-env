from dataclasses import dataclass
from math import isfinite


@dataclass(frozen=True)
class Telemetry:
    tics: int
    position_y: float
    ammo: float
    health: float
    kills: float

    @classmethod
    def read(cls, observation):
        data = observation.structured
        tics = data.get("episode_tics")
        if type(tics) is not int or tics < 0:
            raise ValueError("Doom observations require a nonnegative episode tic")
        variables = data.get("game_variables")
        names = ("POSITION_Y", "AMMO2", "HEALTH", "KILLCOUNT")
        if type(variables) is not dict or not set(names) <= variables.keys():
            raise ValueError("Doom Basic requires POSITION_Y, AMMO2, HEALTH and KILLCOUNT")
        values = [variables[name] for name in names]
        if any(type(value) not in (int, float) or not isfinite(value) for value in values):
            raise ValueError("Doom telemetry must be finite numbers")
        if any(variables[name] < 0 for name in ("AMMO2", "KILLCOUNT")):
            raise ValueError("Doom ammunition and kill counters cannot be negative")
        return cls(tics, *values)
