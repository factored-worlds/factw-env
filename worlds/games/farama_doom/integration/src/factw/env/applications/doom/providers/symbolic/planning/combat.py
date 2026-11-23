"""Priority selection implementing symbolic.plan."""

from ....missions.combat.skills import POSTCONDITIONS, SKILLS


def plan(knowledge, goal):
    if goal != {"mission_complete": True}:
        raise ValueError("Combat mission plans only for native extraction")
    for skill in SKILLS:
        if skill in knowledge["availableActions"]:
            return {"status": "ready", "action": skill, "postcondition": POSTCONDITIONS[skill]}
    facts = knowledge["facts"]
    reason = "unknown_evidence"
    if facts["alive"] is False:
        reason = "dead"
    elif facts["active"] is False:
        reason = "episode_boundary"
    elif facts["has_ammo"] is False and facts["threats_clear"] is False:
        reason = "out_of_ammo"
    return {"status": "blocked", "reason": reason}
