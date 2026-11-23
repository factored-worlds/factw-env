"""Current-RGB grounding for generated predicates, without native-state access.

Evidence admission authenticates references, not perceptual interpretations. This
cooperating-provider boundary does not sandbox arbitrary registered Python code.
"""

import json
from dataclasses import asdict

from ...contracts.goal_estimation import ClauseAssessment, GoalEstimateProposal, Truth
from ...contracts.model_grounding import (
    GeneratedPredicate,
    PredicateAssessment,
    PredicateEstimate,
    PredicateEstimateProposal,
    PredicateEstimationInput,
)
from ...refinement.registry import GroundingBinding
from .goal_grounding import GoalGroundingBoundary

NATIVE_EXIT_CLAUSE = "native_exit_completed"


def _text(value, label):
    if type(value) is not str or not value.strip():
        raise ValueError(f"{label} requires explicit text")


def _sha256(value):
    if (
        type(value) is not str
        or len(value) != 64
        or any(c not in "0123456789abcdef" for c in value)
    ):
        raise ValueError("Candidate revision requires a lowercase SHA256")


class ModelGroundingBoundary:
    def __init__(
        self, *, candidate_sha256, predicates, estimator_id, grounding_revision, public_priors=()
    ):
        _sha256(candidate_sha256)
        if type(predicates) is not tuple or not predicates:
            raise ValueError("Grounding requires an explicit tuple of generated predicates")
        for item in predicates:
            if type(item) is not GeneratedPredicate:
                raise ValueError("Grounding requires typed generated predicates")
            for value in (item.identifier, item.meaning, item.document_id, item.address):
                _text(value, "Generated predicate")
            if item.goal_clause_id is not None:
                _text(item.goal_clause_id, "Goal clause")
        if len({item.identifier for item in predicates}) != len(predicates):
            raise ValueError("Generated predicate identifiers must be unique")
        if len({(item.document_id, item.address) for item in predicates}) != len(predicates):
            raise ValueError("Generated predicate targets must be unique")
        mapped = [item.goal_clause_id for item in predicates if item.goal_clause_id is not None]
        if len(set(mapped)) != len(mapped):
            raise ValueError("Each fixed goal clause permits one generated predicate")
        _text(grounding_revision, "Grounding revision")
        revision = json.dumps(
            {
                "candidate_sha256": candidate_sha256,
                "grounding_revision": grounding_revision,
                "predicates": [asdict(item) for item in predicates],
                "observation_condition": "rgb_only",
            },
            sort_keys=True,
        )
        self._goal = GoalGroundingBoundary(
            estimator_id=estimator_id, grounding_revision=revision, public_priors=public_priors
        )
        if any(item not in {c.identifier for c in self._goal.goal.clauses} for item in mapped):
            raise ValueError("Generated predicates cannot change the fixed goal clause identities")
        self._candidate = candidate_sha256
        self._predicates = predicates
        self._estimator_id = estimator_id
        self._estimate = None

    @property
    def revision_sha256(self):
        return self._goal.revision_sha256

    @property
    def current_estimate(self):
        return self._estimate if self._goal.current_estimate is not None else None

    def start_episode(self):
        self._estimate = None
        return self._goal.start_episode()

    def capture(self, observation):
        self._goal.capture(observation)
        return self.estimator_input()

    def missing_capture(self, capture_id):
        self._goal.missing_capture(capture_id)
        return self.estimator_input()

    def estimator_input(self):
        return PredicateEstimationInput(
            self._candidate, self.revision_sha256, self._goal.estimator_input(), self._predicates
        )

    def estimate(self, estimator):
        request = self.estimator_input()
        if request.observations.capture.rgb is None:
            proposal = PredicateEstimateProposal(
                self._candidate,
                request.observations.episode_id,
                request.observations.capture.capture_id,
                self.revision_sha256,
                tuple(
                    PredicateAssessment(
                        item.identifier, Truth.UNKNOWN, (), "No granted RGB capture"
                    )
                    for item in self._predicates
                ),
            )
        else:
            proposal = estimator.estimate(request)
        return self.accept(proposal)

    def accept(self, proposal):
        request = self.estimator_input()
        observed = request.observations
        if type(proposal) is not PredicateEstimateProposal:
            raise ValueError("Grounding requires a PredicateEstimateProposal")
        if self.current_estimate is not None:
            raise ValueError("The current capture already has an accepted predicate estimate")
        if (
            proposal.candidate_sha256 != self._candidate
            or proposal.revision_sha256 != self.revision_sha256
            or proposal.episode_id != observed.episode_id
            or proposal.capture_id != observed.capture.capture_id
        ):
            raise ValueError("Grounding proposal has stale candidate, revision, episode or capture")
        if (
            type(proposal.assessments) is not tuple
            or len(proposal.assessments) != len(self._predicates)
            or any(type(item) is not PredicateAssessment for item in proposal.assessments)
            or tuple(item.predicate_id for item in proposal.assessments)
            != tuple(item.identifier for item in self._predicates)
        ):
            raise ValueError(
                "Grounding must assess every generated predicate exactly once in order"
            )
        clauses = {}
        for predicate, assessment in zip(self._predicates, proposal.assessments, strict=True):
            self._validate(assessment, observed.capture.evidence)
            if (
                predicate.goal_clause_id == NATIVE_EXIT_CLAUSE
                and assessment.truth is not Truth.UNKNOWN
            ):
                raise ValueError("RGB-only native-exit grounding must remain unknown")
            if predicate.goal_clause_id is not None:
                clauses[predicate.goal_clause_id] = ClauseAssessment(
                    predicate.goal_clause_id,
                    assessment.truth,
                    assessment.evidence,
                    assessment.reason,
                )
        goal = self._goal.accept(
            GoalEstimateProposal(
                observed.episode_id,
                observed.capture.capture_id,
                self.revision_sha256,
                tuple(
                    clauses.get(
                        item.identifier,
                        ClauseAssessment(
                            item.identifier, Truth.UNKNOWN, (), "No generated grounding"
                        ),
                    )
                    for item in observed.goal.clauses
                ),
            )
        )
        self._estimate = PredicateEstimate(
            self._candidate,
            observed.episode_id,
            observed.capture.capture_id,
            self.revision_sha256,
            self._estimator_id,
            proposal.assessments,
            goal,
        )
        return self._estimate

    @staticmethod
    def _validate(assessment, current):
        if type(assessment.truth) is not Truth:
            raise ValueError("Predicate truth requires true, false or unknown")
        _text(assessment.reason, "Predicate interpretation")
        if type(assessment.evidence) is not tuple:
            raise ValueError("Predicate evidence requires typed current capture references")
        for reference in assessment.evidence:
            if current is None or type(reference) is not type(current) or reference != current:
                raise ValueError("Predicate evidence is unavailable, stale, foreign or forged")
            if type(reference.ordinal) is not int:
                raise ValueError("Predicate evidence ordinal requires an integer")
        if assessment.truth is not Truth.UNKNOWN and current not in assessment.evidence:
            raise ValueError("A known generated predicate requires current granted RGB evidence")

    def assessment(self, predicate_id):
        if predicate_id not in {item.identifier for item in self._predicates}:
            raise ValueError(f"Unknown generated predicate: {predicate_id}")
        current = self.current_estimate
        if current is None:
            return PredicateAssessment(
                predicate_id, Truth.UNKNOWN, (), "No current accepted estimate"
            )
        return next(item for item in current.assessments if item.predicate_id == predicate_id)

    def binding(self, predicate_id, *, input_stream_ids):
        predicate = next(
            (item for item in self._predicates if item.identifier == predicate_id), None
        )
        if predicate is None:
            raise ValueError(f"Unknown generated predicate: {predicate_id}")
        if predicate.goal_clause_id == NATIVE_EXIT_CLAUSE:
            raise ValueError("RGB-only grounding cannot register native-exit capability")
        return GroundingBinding(
            predicate.identifier,
            self.revision_sha256,
            predicate.meaning,
            input_stream_ids,
            lambda: self.assessment(predicate_id),
            predicate.goal_clause_id,
        )
