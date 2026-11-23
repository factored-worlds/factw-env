"""Bound provider invocations with native basis and output checks."""

from copy import deepcopy

import smsl
from factw.env.core.state_language.records import decode, encode

from ..bindings.provider import unpack
from ..information.privileged_state import validate_estimate


class Runtime:
    def __init__(self, application, world, providers, *, boundary, planner=None):
        self.bindings = smsl.ApplicationBindings(application, world)
        self.bridge = smsl.WorldBridge(world, "scene")
        registry = smsl.ProviderRegistry()
        self.dispatcher = providers.register(registry, planner=planner, boundary=boundary)
        self.providers = providers
        self.boundary = boundary
        self.session = application.system_definition().session(registry, self.bridge.basis())
        self.failed = False
        self.sequence = 0
        self.calls = []

    def invoke(self, block, inputs=None, *, effects=False):
        self.sequence += 1
        captured = self.bindings.capture(
            block,
            {name: encode(value) for name, value in (inputs or {}).items()},
            sequence=self.sequence,
        )
        captured_inputs = {
            name: unpack(record["value"]) for name, record in captured["inputs"].items()
        }
        active = deepcopy(self.dispatcher.active) if "outcome" in captured["outputs"] else None

        def validate(outputs, call):
            for port, identifier in captured["outputs"].items():
                value = decode(outputs[port]["value"])
                if port == "estimate":
                    validate_estimate(value, scenario=self.boundary.scenario)
                    if (
                        value["tics"]
                        != captured_inputs["observation"]["structured"]["episode_tics"]
                    ):
                        raise ValueError("Estimate tics differ from the captured observation")
                self.providers.validate_output(identifier, value)
                if port == "plan" and value["status"] == "ready":
                    knowledge = captured_inputs["knowledge"]
                    if value["action"] not in knowledge["availableActions"]:
                        raise ValueError(
                            "Planner proposed an action outside captured applicability"
                        )
                if port == "target" and (
                    value["skill"] != captured_inputs["action"]["action"]
                    or value["topology"] != captured_inputs["condition"]
                ):
                    raise ValueError("Refined target differs from the captured action or topology")
                if port == "outcome":
                    invocation = captured_inputs["invocation"]
                    operation = invocation["operation"]
                    expected_status = (
                        "running"
                        if operation == "start"
                        else "cancelled"
                        if operation == "cancel"
                        else invocation["status"]
                    )
                    baseline = invocation if operation == "start" else active
                    if (
                        value["ticket"] != invocation["ticket"]
                        or value["status"] != expected_status
                        or baseline is None
                        or value["skill"] != baseline["skill"]
                        or value["baseline"] != baseline["baseline"]
                        or (operation != "start" and value["reason"] != invocation["reason"])
                    ):
                        raise ValueError("Skill outcome differs from the captured lifecycle")

        completed = False
        try:
            outputs = self.session.invoke(
                block,
                f"{block}-{self.sequence}",
                inputs=captured["inputs"],
                allow_effects=effects,
                current_basis=self.bridge.basis,
                validate_outputs=validate,
            )
            completed = True
        finally:
            if not completed:
                self.failed = True
        values = {port: decode(record["value"]) for port, record in outputs.items()}
        self.calls.append(
            {
                "block": block,
                "sequence": self.sequence,
                "basis": captured["basis"],
                "outputs": values,
                "capture_id": self.boundary.capture_id,
                "access_sha256": self.boundary.digest,
            }
        )
        return values

    def advance(self):
        self.session.advance(self.bridge.basis())

    def close(self):
        self.session.close()
