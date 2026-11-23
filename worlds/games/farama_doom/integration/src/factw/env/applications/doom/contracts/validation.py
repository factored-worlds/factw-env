"""Application payload checks before provider outputs propagate."""

from . import combat
from .lifecycle import validate_outcome


def validate_target(value, *, schema, policy):
    if type(value) is not dict or set(value) != {"skill", "postcondition", "topology"}:
        raise ValueError("Invalid refined target fields")
    if type(value["skill"]) is not str or value["skill"] not in policy.SKILLS:
        raise ValueError("Invalid refined skill")
    if value["postcondition"] != policy.POSTCONDITIONS[value["skill"]]:
        raise ValueError("Invalid refined postcondition")
    schema.scene_spec(value["topology"])


def validate_output(identifier, value, *, prefix, schema, policy, buttons, ground):
    if type(value) is not dict:
        raise ValueError("Doom provider output requires an object")
    if identifier == f"{prefix}.facts.v1":
        schema.validate_facts(value)
    elif identifier == f"{prefix}.command.v1":
        if set(value) != {"buttons"} or not isinstance(value["buttons"], dict):
            raise ValueError("Invalid Doom control command")
        if value["buttons"].keys() - buttons or any(
            type(value) is not int or value != 1 for value in value["buttons"].values()
        ):
            raise ValueError("Doom mission commands require allowlisted binary buttons")
    elif identifier == f"{prefix}.plan.v1":
        if value.get("status") not in ("ready", "blocked"):
            raise ValueError("Invalid planner status")
        if value["status"] == "ready" and value.get("action") not in policy.SKILLS:
            raise ValueError("Invalid planner action")
        if value["status"] == "ready":
            if set(value) != {"status", "action", "postcondition"}:
                raise ValueError("Invalid ready planner fields")
            if value["postcondition"] != policy.POSTCONDITIONS[value["action"]]:
                raise ValueError("Invalid planner postcondition")
        elif set(value) != {"status", "reason"} or type(value["reason"]) is not str:
            raise ValueError("Invalid blocked planner fields")
    elif identifier == f"{prefix}.target.v1":
        validate_target(value, schema=schema, policy=policy)
    elif identifier == f"{prefix}.estimate.v1":
        schema.validate_facts(ground(value))
    elif identifier == f"{prefix}.outcome.v1":
        validate_outcome(value, policy=policy, combat=schema is combat)
    else:
        raise ValueError(f"Unknown application output validator: {identifier}")
