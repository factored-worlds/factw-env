"""Registered, finite button commands for the key-and-exit player interface."""

import json
from dataclasses import dataclass
from types import MappingProxyType

import smsl

BUTTONS = (
    "MOVE_FORWARD",
    "MOVE_BACKWARD",
    "MOVE_LEFT",
    "MOVE_RIGHT",
    "TURN_LEFT",
    "TURN_RIGHT",
    "USE",
)
TICS_PER_SIMULATED_SECOND = 35


@dataclass(frozen=True)
class ButtonCommand:
    buttons: tuple[tuple[str, int], ...]

    def __post_init__(self):
        if (
            type(self.buttons) is not tuple
            or any(type(pair) is not tuple or len(pair) != 2 for pair in self.buttons)
            or any(
                name not in BUTTONS or type(value) is not int or value not in (0, 1)
                for name, value in self.buttons
            )
            or len({name for name, _ in self.buttons}) != len(self.buttons)
        ):
            raise ValueError("Buttons require distinct registered names and binary integers")

    @classmethod
    def from_dict(cls, command):
        if type(command) is not dict or set(command) != {"buttons"}:
            raise ValueError("A primitive accepts only buttons; duration is not a native argument")
        if type(command["buttons"]) is not dict:
            raise ValueError("Buttons must be a named mapping")
        return cls(tuple(command["buttons"].items()))

    def as_dict(self):
        return {"buttons": dict(self.buttons)}


class ButtonBindings:
    def __init__(self, bindings):
        if any(
            type(name) is not str or not name or not isinstance(command, ButtonCommand)
            for name, command in bindings.items()
        ):
            raise ValueError("Register an execution block name and a typed ButtonCommand")
        self._bindings = MappingProxyType(dict(bindings))

    def resolve(self, block):
        if block not in self._bindings:
            raise ValueError(f"Unbound executable leaf: {block}")
        return self._bindings[block]

    def describe(self):
        return {name: command.as_dict() for name, command in self._bindings.items()}


def _inert_outcomes(document):
    outcomes = {"command_applied", "command_failed"}

    def check(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key == "outcomes":
                    continue
                check(key)
                check(item)
        elif isinstance(value, list):
            for item in value:
                check(item)
        elif type(value) is str and value in outcomes:
            raise ValueError("Command outcomes cannot update or ground observation facts")

    for event in document["events"]:
        if event["name"] in outcomes and event["fields"]:
            raise ValueError("Command outcomes have no observation payload")
    check(document["branches"])


def validate_button_composition(definition, world, bindings):
    """Check the effect profile, separately from semantic refinement admission."""
    blocks, documents = definition["blocks"], {}
    for block in blocks.values():
        if block["mechanism"] == "control.operation":
            raise ValueError("Player execution cannot update observation facts through operations")
        if block["mechanism"] != "control.action":
            continue
        instance = block["instance"]
        if instance not in documents:
            documents[instance] = json.loads(
                smsl.dumps(world.snapshot(instance).machine, format="json")
            )
            _inert_outcomes(documents[instance])
        branch = next(
            (
                branch
                for branch in documents[instance]["branches"]
                if branch["name"] == block["branch"]
            ),
            None,
        )
        if branch is None:
            raise ValueError("Primitive branch must exist in its model")
        action = next(
            (action for action in branch["actions"] if action["name"] == block["action"]), None
        )
        if action is None:
            raise ValueError("Primitive action must exist in its model")
        if not {"command_applied", "command_failed"} <= set(action["outcomes"]) or block[
            "success_outcomes"
        ] != ["command_applied"]:
            raise ValueError("Button leaves require separate applied and failed outcomes")
    if set(bindings.describe()) - blocks.keys():
        raise ValueError("A button binding must name an existing execution leaf")
    if any(blocks[name]["mechanism"] != "control.action" for name in bindings.describe()):
        raise ValueError("Button effects can bind only action leaves")
