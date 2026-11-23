"""Player-observation goal estimates; these contracts do not infer native truth."""

from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Protocol

import numpy as np


class Truth(StrEnum):
    TRUE = "true"
    FALSE = "false"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class GoalClause:
    identifier: str
    meaning: str


@dataclass(frozen=True)
class FixedGoal:
    identifier: str
    scenario_id: str
    scenario_behavior_revision: int
    text: str
    sha256: str
    clauses: tuple[GoalClause, ...]
    agent_completion: str
    temporal_scope: str
    revision_rule: str


@dataclass(frozen=True)
class PublicPrior:
    """Explicit authored guidance; its label does not authenticate its contents."""

    identifier: str
    text: str


@dataclass(frozen=True)
class GoalEvidenceReference:
    episode_id: str
    capture_id: str
    ordinal: int
    rgb_sha256: str


@dataclass(frozen=True)
class GrantedGoalCapture:
    capture_id: str
    ordinal: int
    rgb: np.ndarray | None
    evidence: GoalEvidenceReference | None


@dataclass(frozen=True)
class ClauseAssessment:
    clause_id: str
    truth: Truth
    evidence: tuple[GoalEvidenceReference, ...]
    reason: str


@dataclass(frozen=True)
class GoalEstimateProposal:
    episode_id: str
    capture_id: str
    revision_sha256: str
    clauses: tuple[ClauseAssessment, ...]


@dataclass(frozen=True)
class GoalEstimate:
    episode_id: str
    capture_id: str
    revision_sha256: str
    original_goal_sha256: str
    estimator_id: str
    clauses: tuple[ClauseAssessment, ...]

    @property
    def complete(self):
        return bool(self.clauses) and all(clause.truth is Truth.TRUE for clause in self.clauses)

    def as_dict(self):
        return {**asdict(self), "complete": self.complete}


@dataclass(frozen=True)
class GoalEstimationInput:
    goal: FixedGoal
    episode_id: str
    revision_sha256: str
    capture: GrantedGoalCapture
    public_priors: tuple[PublicPrior, ...]
    previous_estimate: GoalEstimate | None


class ObservationGoalEstimator(Protocol):
    def estimate(self, observations: GoalEstimationInput) -> GoalEstimateProposal: ...
