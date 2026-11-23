"""Refine combat actions into targets carrying authored topology."""

from ....missions.combat.skills import POSTCONDITIONS, SKILLS


def refine(action, condition):
    if action.get("branch") != "Scene" or action.get("action") not in SKILLS:
        raise ValueError("Invalid combat symbolic action")
    skill = action["action"]
    return {"skill": skill, "postcondition": POSTCONDITIONS[skill], "topology": condition}
