"""Refine navigation actions into targets carrying authored topology."""

from ....scenarios.retrieve_key_and_escape.skills import POSTCONDITIONS, SKILLS


def refine(action, condition):
    if action.get("branch") != "Scene" or action.get("action") not in SKILLS:
        raise ValueError("Invalid Doom symbolic action")
    skill = action["action"]
    return {"skill": skill, "postcondition": POSTCONDITIONS[skill], "topology": condition}
