"""Closed skill lifecycle values shared by input and output boundaries."""

from math import isfinite


def validate_baseline(value, *, combat):
    fields = {"HEALTH", "AMMO2", "ARMOR", "KILLCOUNT"} if combat else set()
    if type(value) is not dict or set(value) != fields:
        raise ValueError("Doom skill baseline has undeclared fields")
    for name, item in value.items():
        if item is None:
            continue
        if type(item) not in (int, float) or not isfinite(item):
            raise ValueError("Doom skill baseline requires finite measurements or null")
        if name != "HEALTH" and (item < 0 or item != int(item)):
            raise ValueError("Doom skill baseline counts require nonnegative integers or null")


def validate_ticket(value):
    if type(value) is not int or value < 1:
        raise ValueError("Doom skill ticket requires a positive integer")


def validate_invocation(value, *, policy, combat):
    fields = {
        "start": {"operation", "ticket", "skill", "baseline"},
        "finish": {"operation", "ticket", "started_tics", "status", "reason"},
        "cancel": {"operation", "ticket", "reason"},
    }
    if type(value) is not dict or type(value.get("operation")) is not str:
        raise ValueError("Doom execution requires a lifecycle operation")
    operation = value["operation"]
    if operation not in fields or set(value) != fields[operation]:
        raise ValueError("Doom execution has undeclared lifecycle fields")
    validate_ticket(value["ticket"])
    if operation == "start":
        if type(value["skill"]) is not str or value["skill"] not in policy.SKILLS:
            raise ValueError("Doom execution requires a declared skill")
        validate_baseline(value["baseline"], combat=combat)
    else:
        if type(value["reason"]) is not str:
            raise ValueError("Doom execution reason requires text")
        if operation == "finish" and (
            type(value["started_tics"]) is not int
            or value["started_tics"] < 0
            or value["status"] not in ("succeeded", "failed")
        ):
            raise ValueError("Doom completion requires start tics and a terminal status")


def validate_outcome(value, *, policy, combat):
    if type(value) is not dict or value.get("status") not in (
        "running",
        "succeeded",
        "failed",
        "cancelled",
    ):
        raise ValueError("Invalid skill outcome")
    fields = {"ticket", "skill", "baseline", "status"}
    if value["status"] != "running":
        fields.add("reason")
    if set(value) != fields:
        raise ValueError("Doom skill outcome has undeclared fields")
    validate_ticket(value["ticket"])
    if type(value["skill"]) is not str or value["skill"] not in policy.SKILLS:
        raise ValueError("Doom skill outcome requires a declared skill")
    validate_baseline(value["baseline"], combat=combat)
    if "reason" in value and type(value["reason"]) is not str:
        raise ValueError("Doom skill outcome reason requires text")
