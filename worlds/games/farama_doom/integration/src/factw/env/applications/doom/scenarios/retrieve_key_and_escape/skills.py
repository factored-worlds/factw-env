"""Finite action selection and bounded geometry-assisted control."""

from ...providers.subsymbolic.geometry import displacement as displacement

SKILLS = ("collect_key", "approach_door", "open_door", "reach_exit", "wait")
POSTCONDITIONS = {
    "collect_key": "has_key",
    "approach_door": "near_door",
    "open_door": "door_open",
    "reach_exit": "at_exit",
    "wait": "inactive",
}


def confirmed(skill, fresh_facts, baseline=None, estimate=None):
    key = POSTCONDITIONS[skill]
    return fresh_facts["active"] is False if key == "inactive" else fresh_facts[key] is True


def success(updates, facts):
    return (
        all(updates[key] is True for key in ("has_key", "door_open", "at_exit"))
        and facts["task"]["succeeded"] is True
    )


def baseline(estimate):
    return {}


def condition(topology, skill):
    return topology


def lost_evidence(skill, updates, estimate):
    return skill != "wait" and updates[POSTCONDITIONS[skill]] is None


def interruption(skill, updates):
    return None
