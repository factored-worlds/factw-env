"""Generated predicate estimates tied to one admitted player capture."""

from dataclasses import dataclass
from typing import Protocol

from .goal_estimation import GoalEstimate, GoalEstimationInput, GoalEvidenceReference, Truth


@dataclass(frozen=True)
class GeneratedPredicate:
    identifier: str
    meaning: str
    document_id: str
    address: str
    goal_clause_id: str | None = None


@dataclass(frozen=True)
class PredicateAssessment:
    predicate_id: str
    truth: Truth
    evidence: tuple[GoalEvidenceReference, ...]
    reason: str


@dataclass(frozen=True)
class PredicateEstimationInput:
    candidate_sha256: str
    revision_sha256: str
    observations: GoalEstimationInput
    predicates: tuple[GeneratedPredicate, ...]


@dataclass(frozen=True)
class PredicateEstimateProposal:
    candidate_sha256: str
    episode_id: str
    capture_id: str
    revision_sha256: str
    assessments: tuple[PredicateAssessment, ...]


@dataclass(frozen=True)
class PredicateEstimate:
    candidate_sha256: str
    episode_id: str
    capture_id: str
    revision_sha256: str
    estimator_id: str
    assessments: tuple[PredicateAssessment, ...]
    goal_estimate: GoalEstimate


class ObservationPredicateEstimator(Protocol):
    def estimate(self, observations: PredicateEstimationInput) -> PredicateEstimateProposal: ...
