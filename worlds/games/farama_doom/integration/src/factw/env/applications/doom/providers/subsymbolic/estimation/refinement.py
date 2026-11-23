"""Model estimates of generated predicates from a single granted RGB capture."""

import hashlib
from dataclasses import asdict
from types import MappingProxyType

import numpy as np
from jsonschema import Draft202012Validator

from ....contracts.goal_estimation import GoalEvidenceReference, Truth
from ....contracts.model_grounding import (
    PredicateAssessment,
    PredicateEstimateProposal,
    PredicateEstimationInput,
)
from ....information.player_observation.refinement_grounding import NATIVE_EXIT_CLAUSE
from ....refinement.inputs import decode_json_bytes

SCHEMA = "doom.refinement_grounding_result/1"
INSTRUCTIONS = (
    "Estimate every supplied generated predicate using only the current granted RGB image "
    "and explicitly supplied public context. Predicate meanings describe hypotheses, not "
    "observations. A completed command, predicted effect, EXIT sign, missing frame, or generic "
    "termination is not observed completion. Use unknown when current evidence is absent or "
    "ambiguous. Under this RGB-only condition native_exit_completed must be unknown. "
    "Reference only the supplied current capture, never a demonstration or another episode. "
    "Return only the exact JSON result schema."
)


def result_schema(request):
    observed = request.observations
    reference = {
        "type": "object",
        "properties": {
            "episode_id": {"const": observed.episode_id},
            "capture_id": {"const": observed.capture.capture_id},
            "ordinal": {"type": "integer", "const": observed.capture.ordinal},
            "rgb_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
        },
        "required": ["episode_id", "capture_id", "ordinal", "rgb_sha256"],
        "additionalProperties": False,
    }
    properties = {
        "schema": {"const": SCHEMA},
        "candidate_sha256": {"const": request.candidate_sha256},
        "revision_sha256": {"const": request.revision_sha256},
        "episode_id": {"const": observed.episode_id},
        "capture_id": {"const": observed.capture.capture_id},
        "assessments": {
            "type": "array",
            "minItems": len(request.predicates),
            "maxItems": len(request.predicates),
            "items": {
                "type": "object",
                "properties": {
                    "predicate_id": {"enum": [item.identifier for item in request.predicates]},
                    "truth": {"enum": [item.value for item in Truth]},
                    "evidence": {"type": "array", "maxItems": 1, "items": reference},
                    "reason": {"type": "string", "minLength": 1, "pattern": "\\S"},
                },
                "required": ["predicate_id", "truth", "evidence", "reason"],
                "additionalProperties": False,
            },
        },
    }
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


def _unknown(request):
    return PredicateEstimateProposal(
        request.candidate_sha256,
        request.observations.episode_id,
        request.observations.capture.capture_id,
        request.revision_sha256,
        tuple(
            PredicateAssessment(item.identifier, Truth.UNKNOWN, (), "No granted RGB capture")
            for item in request.predicates
        ),
    )


class ObservationRefinementEstimator:
    def __init__(self, transport):
        if not callable(getattr(transport, "generate", None)):
            raise ValueError("Grounding requires an explicitly configured model transport")
        self._transport = transport

    def estimate(self, request):
        if type(request) is not PredicateEstimationInput:
            raise ValueError("Grounding accepts only a PredicateEstimationInput")
        observed = request.observations
        capture = observed.capture
        if capture.rgb is None:
            return _unknown(request)
        rgb = capture.rgb
        if (
            type(rgb) is not np.ndarray
            or rgb.dtype != np.uint8
            or rgb.ndim != 3
            or rgb.shape[2] != 3
            or min(rgb.shape[:2]) < 1
            or capture.evidence is None
        ):
            raise ValueError("Grounding requires an admitted H×W×3 uint8 RGB capture")
        reference = capture.evidence
        if (
            type(reference) is not GoalEvidenceReference
            or any(
                type(value) is not str or not value.strip()
                for value in (observed.episode_id, capture.capture_id)
            )
            or type(capture.ordinal) is not int
            or capture.ordinal < 0
            or type(reference.ordinal) is not int
            or reference.episode_id != observed.episode_id
            or reference.capture_id != capture.capture_id
            or reference.ordinal != capture.ordinal
        ):
            raise ValueError("Grounding evidence disagrees with the current capture identity")
        pixels = rgb.tobytes()
        digest = hashlib.sha256(pixels).hexdigest()
        if capture.evidence.rgb_sha256 != digest:
            raise ValueError("Grounding RGB bytes disagree with the admitted capture hash")
        descriptor = {
            "asset_id": "current_rgb",
            "encoding": "rgb_uint8_hwc",
            "shape": list(rgb.shape),
            "sha256": digest,
        }
        payload = {
            "purpose": "observation_grounding",
            "instructions": INSTRUCTIONS,
            "output_schema": result_schema(request),
            "grounding_request": {
                "candidate_sha256": request.candidate_sha256,
                "revision_sha256": request.revision_sha256,
                "episode_id": observed.episode_id,
                "capture_id": capture.capture_id,
                "observation_condition": "rgb_only",
                "predicates": [asdict(item) for item in request.predicates],
                "fixed_goal": asdict(observed.goal),
                "public_priors": [asdict(item) for item in observed.public_priors],
                "current_evidence": asdict(capture.evidence),
            },
            "observation_sequence": [
                {
                    "stream_id": "player_rgb",
                    "sample_id": capture.capture_id,
                    "ordinal": capture.ordinal,
                    "relative_time": None,
                    "modality": "rgb",
                    "encoding": "rgb_uint8_hwc",
                    "payload_sha256": digest,
                    "content": {"asset_id": "current_rgb", "shape": list(rgb.shape)},
                }
            ],
            "images": [descriptor],
        }
        raw = self._transport.generate(payload, MappingProxyType({"current_rgb": pixels}))
        data = decode_json_bytes(raw)
        errors = tuple(Draft202012Validator(payload["output_schema"]).iter_errors(data))
        if errors:
            raise ValueError(f"Invalid grounding result: {errors[0].message}")
        assessments = tuple(
            PredicateAssessment(
                item["predicate_id"],
                Truth(item["truth"]),
                tuple(GoalEvidenceReference(**reference) for reference in item["evidence"]),
                item["reason"],
            )
            for item in data["assessments"]
        )
        if tuple(item.predicate_id for item in assessments) != tuple(
            item.identifier for item in request.predicates
        ):
            raise ValueError("Grounding result must retain every generated predicate in order")
        for predicate, assessment in zip(request.predicates, assessments, strict=True):
            if (
                predicate.goal_clause_id == NATIVE_EXIT_CLAUSE
                and assessment.truth is not Truth.UNKNOWN
            ):
                raise ValueError("RGB-only native-exit grounding must remain unknown")
        return PredicateEstimateProposal(
            data["candidate_sha256"],
            data["episode_id"],
            data["capture_id"],
            data["revision_sha256"],
            assessments,
        )
