"""Bounded model construction with retained inputs and deterministic admission."""

from dataclasses import dataclass
from pathlib import Path

import smsl

from ....refinement import CandidateAdmission, CandidateReview, GrantedRequest, RefinementRegistry
from .refinement_draft import digest, encoded, materialize_candidate
from .refinement_prompt import discovery_payload


@dataclass(frozen=True)
class DiscoveryResult:
    candidate_bytes: bytes | None
    review: CandidateReview | None
    attempts: int
    audit_directory: Path

    @property
    def valid(self):
        return self.review is not None


class ModelRefinementProvider:
    """A single condition proposal plus at most one public structural repair.

    The supplied transport owns model identity, capabilities, usage and durable
    budget admission. This provider never receives an environment or evaluator.
    """

    def __init__(self, transport, *, registry=None):
        if registry is None:
            registry = RefinementRegistry()
        if type(registry) is not RefinementRegistry:
            raise ValueError("Discovery requires a trusted host binding registry")
        if not callable(getattr(transport, "generate", None)) or not callable(
            getattr(transport, "describe", None)
        ):
            raise ValueError("A configured auditable model transport is required")
        self._transport = transport
        self._registry = registry
        self._used = False

    def discover(self, request, *, audit_directory, max_attempts=2):
        if type(request) is not GrantedRequest:
            raise ValueError("Discovery requires a sealed granted request")
        if type(max_attempts) is not int or max_attempts not in (1, 2):
            raise ValueError("Discovery permits an initial proposal and at most one repair")
        if self._used:
            raise ValueError("This discovery condition has already been attempted")
        admission = CandidateAdmission(request, self._registry)
        configuration = encoded(self._transport.describe())
        directory = Path(audit_directory)
        directory.mkdir(parents=True, exist_ok=False)
        self._used = True
        self._retain_inputs(directory, request, configuration)
        feedback = previous = None
        candidate = review = None
        for ordinal in range(1, max_attempts + 1):
            attempt = directory / f"attempt_{ordinal}"
            attempt.mkdir()
            payload = discovery_payload(
                request, self._registry, feedback=feedback, previous_response=previous
            )
            logical_request = encoded(payload)
            (attempt / "logical_request.json").write_bytes(logical_request)
            self._write_summary(directory, "awaiting_transport", ordinal, None)
            raw = self._transport.generate(payload, request.assets)
            if type(raw) is not bytes:
                raise ValueError("Model transport must return exact UTF-8 response bytes")
            (attempt / "raw_response.bin").write_bytes(raw)
            candidate = None
            try:
                candidate = materialize_candidate(raw, request)
                (attempt / "candidate.json").write_bytes(candidate)
                review = admission.inspect(candidate)
            except (ValueError, smsl.SmslError) as error:
                feedback = str(error)
                (attempt / "validation.json").write_bytes(
                    encoded(
                        {
                            "valid": False,
                            "error_type": type(error).__name__,
                            "public_structural_error": feedback,
                            "raw_response_sha256": digest(raw),
                            "logical_request_sha256": digest(logical_request),
                        }
                    )
                )
                previous = raw
                self._write_summary(directory, "structurally_rejected", ordinal, None)
                continue
            (attempt / "validation.json").write_bytes(
                encoded(
                    {
                        "valid": True,
                        "ready": review.ready,
                        "issues": list(review.issues),
                        "closure_sha256": review.closure_sha256,
                        "document_attribution": review.document_attribution,
                        "candidate_sha256": digest(candidate),
                        "raw_response_sha256": digest(raw),
                        "logical_request_sha256": digest(logical_request),
                        "meaning_or_success_proven": False,
                    }
                )
            )
            self._write_summary(directory, "validated_hypothesis", ordinal, review)
            return DiscoveryResult(candidate, review, ordinal, directory)
        return DiscoveryResult(candidate, None, max_attempts, directory)

    @staticmethod
    def _retain_inputs(directory, request, configuration):
        (directory / "request.json").write_bytes(request.request_bytes)
        (directory / "coverage.json").write_bytes(request.coverage_bytes)
        (directory / "original_goal.json").write_bytes(request.original_goal)
        (directory / "provider_configuration.json").write_bytes(configuration)
        assets = directory / "assets"
        assets.mkdir()
        index = {}
        for ordinal, (identifier, payload) in enumerate(request.assets.items()):
            filename = f"asset_{ordinal:06d}.bin"
            (assets / filename).write_bytes(payload)
            index[identifier] = {"file": filename, "sha256": digest(payload)}
        (assets / "index.json").write_bytes(encoded(index))
        (directory / "input_hashes.json").write_bytes(
            encoded(
                {
                    "request_sha256": request.sha256,
                    "coverage_sha256": digest(request.coverage_bytes),
                    "original_goal_sha256": digest(request.original_goal),
                    "provider_configuration_sha256": digest(configuration),
                    "asset_sha256": {name: digest(data) for name, data in request.assets.items()},
                    "candidate_materialization": "insert_exact_input_and_source_sha256_only",
                }
            )
        )

    @staticmethod
    def _write_summary(directory, status, attempts, review):
        (directory / "result.json").write_bytes(
            encoded(
                {
                    "status": status,
                    "attempts": attempts,
                    "valid": review is not None,
                    "ready": review.ready if review is not None else False,
                    "closure_sha256": review.closure_sha256 if review is not None else None,
                    "executed": False,
                    "goal_success_claimed": False,
                }
            )
        )
