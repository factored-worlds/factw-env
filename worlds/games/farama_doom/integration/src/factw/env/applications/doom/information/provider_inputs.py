"""Mission-specific grants for the six provider contracts."""

from ..contracts import combat, navigation
from ..contracts.lifecycle import validate_invocation
from ..contracts.validation import validate_target
from .privileged_state import COMBAT, NAVIGATION, validate_estimate, validate_reference

PORTS = {
    "subsymbolic.estimate": ({"observation"}, set()),
    "symbolic.ground": ({"estimate"}, set()),
    "symbolic.plan": ({"knowledge", "goal"}, set()),
    "subsymbolic.refine_skill": ({"action", "condition"}, set()),
    "subsymbolic.execute_skill": ({"invocation"}, {"feedback"}),
    "subsymbolic.control_step": ({"target", "estimate"}, set()),
}


def validate_inputs(contract, values, *, scenario):
    from ..missions.combat import skills as combat_skills
    from ..scenarios.retrieve_key_and_escape import skills as navigation_skills

    if scenario not in (NAVIGATION, COMBAT) or contract not in PORTS:
        raise ValueError("Unknown Doom mission provider grant")
    required, optional = PORTS[contract]
    if (
        type(values) is not dict
        or not required <= values.keys()
        or values.keys() - (required | optional)
    ):
        raise ValueError("Doom provider received undeclared input ports")
    schema, policy = (
        (combat, combat_skills) if scenario == COMBAT else (navigation, navigation_skills)
    )
    if contract == "subsymbolic.estimate":
        validate_reference(values["observation"], scenario=scenario)
    if "estimate" in values:
        validate_estimate(values["estimate"], scenario=scenario)
    if contract == "subsymbolic.refine_skill":
        action = values["action"]
        if (
            type(action) is not dict
            or set(action) != {"branch", "action"}
            or action["branch"] != "Scene"
            or type(action["action"]) is not str
            or action["action"] not in policy.SKILLS
        ):
            raise ValueError("Doom refinement requires a declared Scene action")
        schema.scene_spec(values["condition"])
    if contract == "subsymbolic.control_step":
        validate_target(values["target"], schema=schema, policy=policy)
    if contract == "subsymbolic.execute_skill":
        validate_invocation(values["invocation"], policy=policy, combat=scenario == COMBAT)
        feedback = values.get("feedback")
        if values["invocation"]["operation"] == "finish":
            if type(feedback) is not dict or set(feedback) != {"tics", "facts", "estimate"}:
                raise ValueError("Doom completion requires closed observation feedback")
            schema.validate_facts(feedback["facts"])
            validate_estimate(feedback["estimate"], scenario=scenario)
            if (
                type(feedback["tics"]) is not int
                or feedback["tics"] != feedback["estimate"]["tics"]
            ):
                raise ValueError("Doom feedback tics must match its estimate")
        elif "feedback" in values:
            raise ValueError("Doom start and cancel do not accept observation feedback")
    if contract == "symbolic.plan":
        validate_planning(values, schema=schema, policy=policy)


def validate_planning(values, *, schema, policy):
    knowledge = values["knowledge"]
    enums = combat.FACT_ENUMS if schema is combat else {"region": ("key_room", "exit_room")}
    counts = combat.FACT_COUNTS if schema is combat else {}
    facts = (
        {*combat.BOOLEANS, *enums, *counts} if schema is combat else {"active", *navigation.FACTS}
    )
    goal = {"mission_complete": True} if schema is combat else {"native_exit": True}
    if (
        type(knowledge) is not dict
        or set(knowledge) != {"facts", "availableActions"}
        or type(knowledge["facts"]) is not dict
        or set(knowledge["facts"]) != facts
        or type(values["goal"]) is not dict
        or values["goal"] != goal
        or type(next(iter(values["goal"].values()))) is not bool
    ):
        raise ValueError("Doom planner view does not match its declared domain")
    for key, item in knowledge["facts"].items():
        if item is None or item == {"kind": "unknown"}:
            continue
        if key in enums:
            allowed = item in enums[key]
        elif key in counts:
            allowed = type(item) is int and 0 <= item <= counts[key]
        else:
            allowed = type(item) is bool
        if not allowed:
            raise ValueError("Doom planner facts have undeclared values")
    if type(knowledge["availableActions"]) is not list or any(
        type(action) is not str or action not in policy.SKILLS
        for action in knowledge["availableActions"]
    ):
        raise ValueError("Doom planner actions require declared action identifiers")
