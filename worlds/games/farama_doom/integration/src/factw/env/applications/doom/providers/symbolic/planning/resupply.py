"""Local replacement: replenish ammunition before the usual combat priorities."""

from ....host.planner import PlannerBinding
from ....information.privileged_state import COMBAT
from ....missions.combat.skills import DODGE_SKILLS, POSTCONDITIONS
from .combat import plan as priority_plan


def plan(knowledge, goal):
    available = knowledge["availableActions"]
    if "resupply" in available and not any(skill in available for skill in DODGE_SKILLS):
        return {
            "status": "ready",
            "action": "resupply",
            "postcondition": POSTCONDITIONS["resupply"],
        }
    return priority_plan(knowledge, goal)


def binding():
    return PlannerBinding("doom.demo.resupply-first", COMBAT, plan)
