"""Control combat buttons using native pose, object labels and authored topology."""

from math import atan2, cos, degrees, hypot, radians, sin

DODGE_BUTTONS = {"dodge_left": "MOVE_LEFT", "dodge_right": "MOVE_RIGHT"}


def route(skill, values, topology):
    x, y = values["POSITION_X"], values["POSITION_Y"]
    if skill in ("heal", "resupply", "equip_armor"):
        if x > 448:
            return topology["arena_entry"]
        if x > 304:
            return topology["supply_approach"]
        return topology[{"heal": "health", "resupply": "ammo", "equip_armor": "armor"}[skill]]
    if x < 272:
        return topology["supply_approach"]
    if x < 400:
        return topology["arena_entry"]
    if skill in ("advance_arena", "collect_key", "approach_door"):
        return topology[
            {
                "advance_arena": "arena_entry",
                "collect_key": "key",
                "approach_door": "door_approach",
            }[skill]
        ]
    if x < 848:
        return topology["door_crossing"]
    if skill == "heal_reserve":
        return topology["reserve_health"]
    if skill == "approach_reactor":
        return topology["reactor"]
    if skill == "extract":
        if x < 1104 and abs(y - topology["extraction_approach"][1]) > 12:
            return topology["extraction_approach"]
        return topology["extraction_crossing" if x < 1200 else "exit"]
    raise ValueError(f"No route for combat skill: {skill}")


def control(target, estimate):
    skill, values, topology = target["skill"], estimate["measurements"], target["topology"]
    if skill in DODGE_BUTTONS:
        return {"buttons": {DODGE_BUTTONS[skill]: 1}}
    if skill == "wait" or (skill == "activate_reactor" and values["USER4"] == 1):
        return {"buttons": {}}
    if skill == "search":
        return {"buttons": {"TURN_LEFT": 1}}
    x, y, angle = (values[key] for key in ("POSITION_X", "POSITION_Y", "ANGLE"))
    if any(value is None for value in (x, y, angle)):
        raise ValueError("Combat control requires current observed pose")
    button = "MOVE_FORWARD"
    if skill == "dodge_to_open_side":
        center_x, center_y = topology["supply_approach"]
        heading = radians(angle)
        left = (center_y - y) * cos(heading) - (center_x - x) * sin(heading) >= 0
        return {"buttons": {"MOVE_LEFT" if left else "MOVE_RIGHT": 1}}
    if skill in ("open_door", "activate_reactor"):
        heading = topology["door_direction" if skill == "open_door" else "reactor_direction"]
        button = "USE"
    else:
        if skill == "engage":
            labels = estimate["labels"]
            if labels is None:
                raise ValueError("Combat aim requires current visible native labels")
            monsters = [label for label in labels if label["category"] == "Monster"]
            if not monsters:
                return {"buttons": {"TURN_LEFT": 1}}
            closest = min(
                monsters, key=lambda item: hypot(item["position"][0] - x, item["position"][1] - y)
            )
            target_x, target_y = closest["position"][:2]
            button = "ATTACK"
        else:
            target_x, target_y = route(skill, values, topology)
        heading = degrees(atan2(target_y - y, target_x - x))
    error = (heading - angle + 180) % 360 - 180
    if abs(error) > 2.0:
        return {"buttons": {"TURN_LEFT" if error > 0 else "TURN_RIGHT": 1}}
    if button == "MOVE_FORWARD":
        close = hypot(target_x - x, target_y - y) < 120
        precision = skill in ("approach_door", "approach_reactor") or (
            skill == "extract" and [target_x, target_y] == topology["extraction_approach"]
        )
        if close and precision and estimate["tics"] % 4 != 0:
            return {"buttons": {}}
    return {"buttons": {button: 1}}
