"""Prepare one explicit RGB composition without starting a model or simulator."""

from dataclasses import dataclass

from ..bindings.button_primitives import ButtonCommand
from ..providers.model_transport import MODEL
from ..refinement import CandidateAdmission, PrimitiveBinding, RefinementRegistry
from ..refinement.inputs import decode_json_bytes
from ..runtime.refinement_observations import RefinementObservations


def primitive_bindings(payload):
    value = decode_json_bytes(payload)
    if (
        type(value) is not dict
        or set(value) != {"schema", "primitives"}
        or value["schema"] != "doom.primitive_bindings/1"
        or type(value["primitives"]) is not list
    ):
        raise ValueError("Expected a closed doom.primitive_bindings/1 host document")
    result = []
    for item in value["primitives"]:
        if type(item) is not dict or set(item) != {
            "identifier",
            "revision",
            "contract_id",
            "command",
        }:
            raise ValueError(
                "Each host primitive requires its exact identity, revision and command"
            )
        result.append(
            PrimitiveBinding(
                item["identifier"],
                item["revision"],
                item["contract_id"],
                ButtonCommand.from_dict(item["command"]),
            )
        )
    if len({item.identifier for item in result}) != len(result):
        raise ValueError("Host primitive identifiers must be unique")
    return tuple(result)


@dataclass(frozen=True)
class PreparedComposition:
    observations: RefinementObservations
    admission: CandidateAdmission
    review: object

    def describe(self):
        return {
            "schema": "doom.refinement_composition/1",
            "candidate_sha256": self.observations.candidate_sha256,
            "request_sha256": self.observations.request_sha256,
            "closure_sha256": self.review.closure_sha256,
            "information_profile": "player-observation",
            "observation_condition": "rgb_only",
            "model": MODEL,
            "agent_available": self.review.ready,
            "issues": list(self.review.issues),
            "registry": self.admission.registry.describe(),
            "executed": False,
            "goal_success_claimed": False,
        }


def prepare_composition(request, candidate_bytes, primitives=()):
    observations = RefinementObservations(
        request,
        candidate_bytes,
        estimator_id="openai_rgb_predicates",
        grounding_revision=f"observed_fact_projection_1:{MODEL}",
    )
    registry = RefinementRegistry(
        groundings=observations.bindings,
        primitives=primitives,
        observable_goal_clauses=("blue_key_acquired", "physical_door_opened"),
        observation_condition="rgb_only",
    )
    admission = CandidateAdmission(request, registry)
    review = admission.inspect(candidate_bytes)
    return PreparedComposition(observations, admission, review)
