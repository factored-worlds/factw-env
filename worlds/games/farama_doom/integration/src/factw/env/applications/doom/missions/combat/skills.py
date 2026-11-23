"""Resource-aware symbolic priorities and visible-target feedback control."""

from ...providers.subsymbolic.geometry import displacement as displacement

DODGE_SKILLS = ("dodge_to_open_side", "dodge_left", "dodge_right")
SKILLS = (
    *DODGE_SKILLS,
    "heal",
    "resupply",
    "equip_armor",
    "heal_reserve",
    "engage",
    "advance_arena",
    "search",
    "collect_key",
    "approach_door",
    "open_door",
    "approach_reactor",
    "activate_reactor",
    "extract",
    "wait",
)
POSTCONDITIONS = {
    **dict.fromkeys(DODGE_SKILLS, "fireball_path_clear"),
    "heal": "health_increased",
    "resupply": "ammo_increased",
    "equip_armor": "armor_increased",
    "heal_reserve": "health_increased",
    "engage": "kill_observed",
    "advance_arena": "arena",
    "search": "threat",
    "collect_key": "has_key",
    "approach_door": "near_door",
    "open_door": "door_open",
    "approach_reactor": "near_reactor",
    "activate_reactor": "extraction_open",
    "extract": "at_exit",
    "wait": "inactive",
}
RESOURCE_VARIABLES = {
    "heal": "HEALTH",
    "heal_reserve": "HEALTH",
    "resupply": "AMMO2",
    "equip_armor": "ARMOR",
    "engage": "KILLCOUNT",
}


def condition(topology, skill):
    return topology


def baseline(estimate):
    return {key: estimate["measurements"][key] for key in ("HEALTH", "AMMO2", "ARMOR", "KILLCOUNT")}


def confirmed(skill, fresh_facts, baseline, estimate):
    if skill in DODGE_SKILLS:
        return fresh_facts["incoming_fireball"] is False
    if skill in RESOURCE_VARIABLES:
        key = RESOURCE_VARIABLES[skill]
        before, after = baseline[key], estimate["measurements"][key]
        return before is not None and after is not None and after > before
    if skill == "activate_reactor":
        return fresh_facts["reactor_active"] is True and fresh_facts["extraction_open"] is True
    if skill == "advance_arena":
        return fresh_facts["region"] == "arena"
    if skill == "wait":
        return fresh_facts["active"] is False and fresh_facts["at_exit"] is True
    return fresh_facts[POSTCONDITIONS[skill]] is True


def success(updates, facts):
    return (
        all(
            updates[key] is True
            for key in (
                "alive",
                "has_key",
                "door_open",
                "reactor_active",
                "extraction_open",
                "threats_clear",
                "at_exit",
            )
        )
        and facts["task"]["succeeded"] is True
    )


def lost_evidence(skill, updates, estimate):
    required = {"alive", "has_ammo", "health_low", "region"}
    if skill in ("engage", "search"):
        required.add("threat")
    elif skill not in RESOURCE_VARIABLES and skill not in (*DODGE_SKILLS, "advance_arena", "wait"):
        required.add(POSTCONDITIONS[skill])
    return any(updates[key] is None for key in required)


def interruption(skill, updates):
    if updates["incoming_fireball"] is True:
        if updates["region"] == "supply":
            dodge = "dodge_to_open_side"
        else:
            dodge = "dodge_right" if updates["fireball_pass_side"] == "left" else "dodge_left"
        return "incoming_fireball" if skill != dodge else None
    if skill in DODGE_SKILLS:
        return "fireball_evidence_lost"
    if updates["health_low"] is True:
        if updates["health_available"] is True and skill != "heal":
            return "health_priority"
        if (
            updates["reserve_health_available"] is True
            and updates["door_open"] is True
            and skill not in ("heal", "heal_reserve")
        ):
            return "health_priority"
    if (
        updates["ammo_low"] is True
        and updates["ammo_available"] is True
        and skill not in ("heal", "heal_reserve", "resupply")
    ):
        return "ammunition_priority"
    if skill in ("engage", "search") and updates["has_ammo"] is False:
        return "ammunition_depleted"
    if skill == "engage" and updates["threat"] is False:
        return "target_lost"
    if (
        updates["threat"] is True
        and updates["has_ammo"] is True
        and skill not in ("heal", "heal_reserve", "resupply", "equip_armor", "engage")
    ):
        return "visible_threat"
    return None
