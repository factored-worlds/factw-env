"""Validate hypotheses, seal their closure, then activate a fresh host execution."""

import hashlib
import json
from dataclasses import dataclass

from ..information.player_observation.goal_grounding import fixed_goal
from ..runtime.primitive_execution import PrimitiveExecution
from .correspondence import check_correspondence
from .documents import LinkedDocuments
from .inputs import GrantedRequest, decode_json_bytes, validate_candidate_bytes
from .registry import RefinementRegistry


def _sha(payload):
    return hashlib.sha256(payload).hexdigest()


def _encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


@dataclass(frozen=True)
class CandidateReview:
    closure_sha256: str
    issues: tuple[str, ...]
    _source: bytes
    _attribution: tuple[tuple[str, str], ...]

    @property
    def ready(self):
        return not self.issues

    @property
    def candidate(self):
        return decode_json_bytes(self._source)

    @property
    def document_attribution(self):
        return dict(self._attribution)


class CandidateAdmission:
    """This handle belongs to the host; give providers only projected requests."""

    def __init__(self, request, registry):
        if type(request) is not GrantedRequest or type(registry) is not RefinementRegistry:
            raise ValueError("Admission requires a granted request and a trusted host registry")
        if _sha(request.original_goal) != fixed_goal().sha256:
            raise ValueError("The Doom pilot's original goal is fixed")
        clauses = {item["id"] for item in request.request["original_goal"]["document"]["clauses"]}
        if not set(registry.observable_goal_clauses) <= clauses:
            raise ValueError("Host capabilities name an unknown fixed goal clause")
        if any(
            not set(item.input_stream_ids) <= request.streams.keys() for item in registry.groundings
        ):
            raise ValueError("A registered grounding requests unavailable or private streams")
        self._request, self._registry = request, registry
        self._reviews = {}
        self._active = self._active_closure = None

    @property
    def active(self):
        return self._active

    @property
    def registry(self):
        return self._registry

    @property
    def request_sha256(self):
        return self._request.sha256

    @property
    def active_closure(self):
        return self._active_closure

    def _validate(self, payload):
        candidate = validate_candidate_bytes(payload, self._request)
        documents = LinkedDocuments(candidate)
        evidence = {item["id"] for item in candidate["evidence"]}
        for collection in (
            "goal_correspondence",
            "state_correspondence",
            "action_refinements",
            "grounding",
        ):
            for item in candidate[collection]:
                references = item["evidence_ids"]
                if len(references) != len(set(references)) or not set(references) <= evidence:
                    raise ValueError(
                        "Correspondence and grounding require existing unique evidence IDs"
                    )
        issues, bindings = check_correspondence(candidate, documents, self._request, self._registry)
        record = {
            "candidate_sha256": _sha(payload),
            "request_sha256": self._request.sha256,
            "coverage_sha256": _sha(self._request.coverage_bytes),
            "original_goal_sha256": _sha(self._request.original_goal),
            "assets": {name: _sha(value) for name, value in self._request.assets.items()},
            "linked_definitions": documents.canonical,
            "registry": self._registry.describe(),
            "issues": issues,
        }
        priors = self._request.request.get("guidance", {}).get("prior_smsl_documents", [])
        prior_hashes = {item["sha256"] for item in priors}
        prior_ids = {item["id"] for item in priors}
        attribution = tuple(
            (
                item["id"],
                "exact_prior_source"
                if item["sha256"] in prior_hashes
                else "changed_prior_document_id"
                if item["id"] in prior_ids
                else "no_exact_prior_match",
            )
            for item in candidate["documents"]
        )
        return (
            CandidateReview(_sha(_encoded(record)), issues, payload, attribution),
            documents,
            bindings,
        )

    def inspect(self, payload):
        review, _, _ = self._validate(payload)
        self._reviews[id(review)] = review
        return review

    def activate(self, review, *, reviewed_closure, environment, episode_id):
        if type(review) is not CandidateReview or self._reviews.get(id(review)) is not review:
            raise ValueError("Activation requires a review issued by this admission")
        current, documents, bindings = self._validate(review._source)
        if (
            not current.ready
            or current.closure_sha256 != review.closure_sha256
            or type(reviewed_closure) is not str
            or reviewed_closure != current.closure_sha256
        ):
            raise ValueError(
                "Activation requires the complete ready closure's explicit host review"
            )
        if self._active is not None and self._active.inspect()["status"] not in {
            "idle",
            "success",
            "failure",
        }:
            raise ValueError("Halt and acknowledge pending execution before replacing its closure")
        if self._active is not None and self._active.dispatch_count:
            raise ValueError("A run with native effects is frozen; start a fresh host and episode")
        root = documents.execution_block(current.candidate["entrypoints"]["execution"])
        identifier = root["document_id"]
        execution = PrimitiveExecution(
            documents.executions[identifier],
            documents.world(),
            environment,
            bindings[identifier],
            episode_id=episode_id,
        )
        if self._active is not None:
            self._active.retire()
        self._active, self._active_closure = execution, current.closure_sha256
        return execution
