"""Ground combat facts from native mission telemetry and object labels."""

from ....contracts.combat import FLAGS, REGIONS
from .imp_fireballs import FireballTrack, visible_fireballs


def make_grounder():
    track = FireballTrack()

    def observe(estimate):
        current = visible_fireballs(estimate)
        return ground(estimate, fireball_pass_side=track.observe(estimate, current))

    return observe


def ground(value, *, fireball_pass_side=None):
    measurements, labels = value["measurements"], value["labels"]
    fireballs = visible_fireballs(value)
    count = None if fireballs is None else len(fireballs)
    if count == 0:
        fireball_pass_side = "none"

    def compare(name, predicate):
        item = measurements[name]
        return None if item is None else predicate(item)

    return {
        "active": value["active"],
        "alive": compare("HEALTH", lambda x: x > 0),
        "health_low": compare("HEALTH", lambda x: x <= 35),
        "ammo_low": compare("AMMO2", lambda x: x <= 8),
        "has_ammo": compare("AMMO2", lambda x: x > 0),
        "armored": compare("ARMOR", lambda x: x > 0),
        "visible_fireball_count": count,
        "fireball_visible": None if count is None else count > 0,
        "incoming_fireball": (None if fireball_pass_side is None else fireball_pass_side != "none"),
        "fireball_pass_side": fireball_pass_side,
        "threats_clear": compare("USER5", lambda x: x == 0),
        "threat": None if labels is None else any(item["category"] == "Monster" for item in labels),
        **{key: compare(variable, bool) for key, variable in FLAGS.items()},
        "region": REGIONS.get(measurements["USER13"]),
    }
