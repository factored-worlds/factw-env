"""Explicit Doom views for cooperating providers; this is not a Python sandbox."""

import hashlib
import json
from copy import deepcopy
from uuid import uuid4

from factw.env.core.core import AgentObservation

from .basic_policy import policy_input
from .evaluation_view import evaluation_view
from .privileged_state import (
    BASIC,
    reference_view,
)
from .profiles import require_agent_profile
from .provider_inputs import validate_inputs


class InformationBoundary:
    def __init__(self, scenario, *, profile="reference-assisted"):
        policy = require_agent_profile(scenario, profile)["policy"]
        self.scenario, self.profile = scenario, profile
        self.variables = tuple(policy["provider_reference_fields"][1:])
        self.policy = policy
        self.digest = hashlib.sha256(json.dumps(policy, sort_keys=True).encode()).hexdigest()
        self.clear()

    def clear(self):
        self.capture_id = self._native = None
        self._terminated = self._truncated = None

    def capture(self, observation, *, terminated, truncated):
        self.clear()
        if not isinstance(observation, AgentObservation):
            raise ValueError("Doom capture requires a native agent observation")
        if type(terminated) is not bool or type(truncated) is not bool:
            raise ValueError("Doom capture requires Boolean boundary flags")
        native = AgentObservation(structured=observation.structured)
        self._native = native
        self._terminated, self._truncated = terminated, truncated
        self.capture_id = uuid4().hex
        return self.capture_id

    def _require_capture(self):
        if self._native is None:
            raise RuntimeError("Capture native evidence before requesting Doom information views")

    def reference_inputs(self):
        self._require_capture()
        return reference_view(
            self._native,
            scenario=self.scenario,
            active=not (self._terminated or self._truncated),
        )

    def evaluation_inputs(self):
        self._require_capture()
        return evaluation_view(
            self._native,
            scenario=self.scenario,
            capture_id=self.capture_id,
            terminated=self._terminated,
            truncated=self._truncated,
        )

    def basic_policy_inputs(self, *, facts, position_y, basis):
        if self.scenario != BASIC:
            raise ValueError("Doom Basic policy input requires the Basic scenario")
        return policy_input(
            facts=facts,
            position_y=position_y,
            capture_id=self.capture_id,
            access_sha256=self.digest,
            basis=basis,
        )

    def provider_inputs(self, contract, values):
        validate_inputs(contract, values, scenario=self.scenario)
        return deepcopy(values)

    def describe(self):
        return {**deepcopy(self.policy), "sha256": self.digest}
