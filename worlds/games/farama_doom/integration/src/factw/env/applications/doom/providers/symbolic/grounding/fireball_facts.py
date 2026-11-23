"""Ground visible native projectiles as independently observed SMSL instances."""

from math import hypot

import smsl

from .imp_fireballs import visible_fireballs

UNITS = 100
COORDINATE_ZERO = 1 << 31
MAX_READING = (1 << 32) - 1
AXES = ("x", "y", "z")
EVENT = "observed_fireball"


def _reading(value, origin=0):
    encoded = round(value * UNITS) + origin
    if not 0 <= encoded <= MAX_READING:
        raise ValueError("Fireball reading is outside the model's fixed-point range")
    return encoded


def _payload(identity, position, player_x, player_y):
    if not 0 <= identity <= MAX_READING:
        raise ValueError("Fireball ID is outside the model's unsigned ID range")
    x, y, _ = position
    return {
        "id": identity,
        **{
            axis: _reading(value, COORDINATE_ZERO)
            for axis, value in zip(AXES, position, strict=True)
        },
        "horizontal_distance": (
            None
            if player_x is None or player_y is None
            else _reading(hypot(x - player_x, y - player_y))
        ),
    }


class FireballFacts:
    """Publish signed positions and horizontal ranges to hundredths of a Doom map unit.

    An unsigned coordinate reading of 2**31 represents zero. A distance reading
    of zero represents zero distance. IDs are the native visible label IDs.
    """

    def __init__(self, world, model_source: bytes, *, scope: str, clock: str):
        self._world = world
        self._machine = smsl.loads(model_source.decode("utf-8"))
        self._scope = scope
        self._clock = clock
        self._current = None

    def observe(self, estimate, *, tick: int):
        """Commit one grounded event per visible fireball and return its evidence."""
        visible = visible_fireballs(estimate)
        measurements = estimate["measurements"]
        player_x, player_y = measurements["POSITION_X"], measurements["POSITION_Y"]
        reports = {
            identity: _payload(identity, position, player_x, player_y)
            for identity, position in (visible or {}).items()
        }
        current = {identity: f"fireball_{identity}" for identity in sorted(reports)}
        previous = self._current or {}
        for identity in previous.keys() - current.keys():
            self._world.remove(previous[identity])

        observations = []
        for identity, name in current.items():
            if identity in previous:
                snapshot = self._world.snapshot(name)
            else:
                context = smsl.Context(f"{self._scope}/{name}/{tick}", name, self._clock)
                snapshot = self._world.spawn(name, self._machine, context)
            payload = reports[identity]
            transition = self._world.advance(
                name, smsl.Event(EVENT, tick, snapshot.context, payload=payload)
            )
            ref = transition.event_ref
            observations.append(
                {
                    "branch": name,
                    "event": EVENT,
                    "payload": payload,
                    "ref": {"scope": ref.scope, "step": ref.step},
                    "source": "native_grounding",
                }
            )
        self._current = None if visible is None else current
        return observations

    def facts(self):
        """Read the current projectile facts as display values, or None if unavailable."""
        if self._current is None:
            return None

        result = []
        for name in self._current.values():
            facts = self._world.snapshot(name).facts("Fireball")
            distance = facts["horizontal_distance"]
            result.append(
                {
                    "id": facts["id"],
                    **{axis: (facts[axis] - COORDINATE_ZERO) / UNITS for axis in AXES},
                    "horizontal_distance": None if distance is smsl.UNKNOWN else distance / UNITS,
                }
            )
        return result
