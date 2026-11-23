"""Priority selection implementing symbolic.plan."""

from ....scenarios.retrieve_key_and_escape.skills import POSTCONDITIONS, SKILLS


def plan(knowledge, goal):
    if goal != {"native_exit": True}:
        raise ValueError("Doom navigation plans only for the native exit")
    facts, available = knowledge["facts"], knowledge["availableActions"]
    for skill in SKILLS:
        if skill in available:
            return {"status": "ready", "action": skill, "postcondition": POSTCONDITIONS[skill]}
    reason = (
        "episode_boundary"
        if facts["active"] is False
        else ("dead" if facts["alive"] is False else "unknown_evidence")
    )
    return {"status": "blocked", "reason": reason}
