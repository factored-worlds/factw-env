"""Control navigation buttons using native pose and authored topology."""

from math import atan2, degrees, hypot


def control(target, estimate):
    skill = target["skill"]
    if skill == "wait":
        return {"buttons": {}}
    values, topology = estimate["measurements"], target["topology"]
    x, y, angle = (values[key] for key in ("POSITION_X", "POSITION_Y", "ANGLE"))
    if any(value is None for value in (x, y, angle)):
        raise ValueError("Control requires current observed pose")
    use = skill == "open_door" and values["USER4"] == 1
    if use:
        heading = topology["door_direction"]
    else:
        key = "key_position" if skill == "collect_key" else "door_approach"
        if skill == "reach_exit":
            cross_x, cross_y = topology["door_crossing"]
            from_x, from_y = topology["door_approach"]
            progress = (x - cross_x) * (cross_x - from_x) + (y - cross_y) * (cross_y - from_y)
            key = "door_crossing" if progress < 0 else "exit_position"
        target_x, target_y = topology[key]
        heading = degrees(atan2(target_y - y, target_x - x))
    error = (heading - angle + 180) % 360 - 180
    if abs(error) > 7.1:
        return {"buttons": {"TURN_LEFT" if error > 0 else "TURN_RIGHT": 1}}
    # Coast between short forward pushes so momentum cannot carry us past the door.
    if not use and skill in {"approach_door", "open_door"}:
        if hypot(target_x - x, target_y - y) < 104 and estimate["tics"] % 12 >= 4:
            return {"buttons": {}}
    return {"buttons": {"USE" if use else "MOVE_FORWARD": 1}}
