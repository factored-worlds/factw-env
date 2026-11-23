"""Episode-scoped evidence boundary for cooperating observation estimators.

Only references and information grants are checked here. A matching RGB reference
does not establish that an estimator's interpretation is perceptually correct.
This is a host boundary, not a sandbox for arbitrary Python providers.
"""

import hashlib
import json
from importlib.resources import files
from uuid import uuid4

import numpy as np

from ...contracts.goal_estimation import (
    ClauseAssessment,
    FixedGoal,
    GoalClause,
    GoalEstimate,
    GoalEstimateProposal,
    GoalEstimationInput,
    GoalEvidenceReference,
    GrantedGoalCapture,
    PublicPrior,
    Truth,
)
from . import PlayerObservation

PERSISTENT_CLAUSES = frozenset({"blue_key_acquired", "physical_door_opened"})


def fixed_goal():
    raw = files("factw.env.applications.doom.contracts").joinpath(
        "retrieve_key_and_escape_goal.json"
    )
    data = raw.read_bytes()
    goal = json.loads(data)
    return FixedGoal(
        goal["id"],
        goal["scenario_id"],
        goal["scenario_behavior_revision"],
        goal["text"],
        hashlib.sha256(data).hexdigest(),
        tuple(GoalClause(item["id"], item["meaning"]) for item in goal["clauses"]),
        goal["agent_completion"],
        goal["temporal_scope"],
        goal["revision_rule"],
    )


def _identifier(value, label):
    if type(value) is not str or not value.strip():
        raise ValueError(f"{label} requires a nonempty identifier")


class GoalGroundingBoundary:
    def __init__(self, *, estimator_id, grounding_revision, public_priors=()):
        _identifier(estimator_id, "Estimator")
        _identifier(grounding_revision, "Grounding revision")
        if type(public_priors) is not tuple or any(
            type(prior) is not PublicPrior for prior in public_priors
        ):
            raise ValueError("Public priors require an explicit tuple of PublicPrior records")
        for prior in public_priors:
            _identifier(prior.identifier, "Public prior")
            if type(prior.text) is not str or not prior.text.strip():
                raise ValueError("Public prior requires explicit text")
        if len({prior.identifier for prior in public_priors}) != len(public_priors):
            raise ValueError("Public prior identifiers must be unique")
        self._goal = fixed_goal()
        self._estimator_id = estimator_id
        self._priors = public_priors
        closure = {
            "goal_sha256": self._goal.sha256,
            "estimator_id": estimator_id,
            "grounding_revision": grounding_revision,
            "public_priors": [(prior.identifier, prior.text) for prior in public_priors],
        }
        self._revision = hashlib.sha256(json.dumps(closure, sort_keys=True).encode()).hexdigest()
        self._episode_id = None
        self._capture = self._estimate = None
        self._captures = {}
        self._accepted = False

    @property
    def goal(self):
        return self._goal

    @property
    def revision_sha256(self):
        return self._revision

    @property
    def current_estimate(self):
        return self._estimate if self._accepted else None

    def start_episode(self):
        self._episode_id = uuid4().hex
        self._capture = self._estimate = None
        self._captures.clear()
        self._accepted = False
        return self._episode_id

    def capture(self, observation):
        if type(observation) is not PlayerObservation:
            raise ValueError("Goal estimation accepts only a detached PlayerObservation")
        rgb = observation.rgb
        if (
            type(rgb) is not np.ndarray
            or rgb.dtype != np.uint8
            or rgb.ndim != 3
            or rgb.shape[2] != 3
            or min(rgb.shape[:2]) < 1
        ):
            raise ValueError("Goal capture requires H×W×3 uint8 RGB")
        pixels = np.frombuffer(rgb.tobytes(), dtype=np.uint8).reshape(rgb.shape)
        return self._capture_input(observation.capture_id, pixels)

    def missing_capture(self, capture_id):
        return self._capture_input(capture_id, None)

    def _capture_input(self, capture_id, rgb):
        if self._episode_id is None:
            raise RuntimeError("Start an episode before admitting player captures")
        _identifier(capture_id, "Capture")
        if capture_id in self._captures:
            raise ValueError("Capture identifiers cannot be reused within an episode")
        ordinal = len(self._captures)
        evidence = None
        if rgb is not None:
            evidence = GoalEvidenceReference(
                self._episode_id, capture_id, ordinal, hashlib.sha256(rgb.tobytes()).hexdigest()
            )
        self._capture = GrantedGoalCapture(capture_id, ordinal, rgb, evidence)
        self._captures[capture_id] = self._capture
        self._accepted = False
        return self.estimator_input()

    def estimator_input(self):
        if self._capture is None:
            raise RuntimeError("Admit a player capture before requesting goal estimation")
        return GoalEstimationInput(
            self._goal,
            self._episode_id,
            self._revision,
            self._capture,
            self._priors,
            self._estimate,
        )

    def estimate(self, estimator):
        return self.accept(estimator.estimate(self.estimator_input()))

    def accept(self, proposal):
        request = self.estimator_input()
        if type(proposal) is not GoalEstimateProposal:
            raise ValueError("Goal estimator must return a GoalEstimateProposal")
        if self._accepted:
            raise ValueError("The current capture already has an accepted goal estimate")
        if any(
            type(value) is not str
            for value in (proposal.episode_id, proposal.capture_id, proposal.revision_sha256)
        ):
            raise ValueError("Goal proposal identities require strings")
        if (
            proposal.episode_id != self._episode_id
            or proposal.capture_id != request.capture.capture_id
            or proposal.revision_sha256 != self._revision
        ):
            raise ValueError("Goal proposal has stale episode, capture or grounding revision")
        if type(proposal.clauses) is not tuple or len(proposal.clauses) != len(self._goal.clauses):
            raise ValueError("Goal estimate must assess every fixed clause exactly once")
        expected = tuple(clause.identifier for clause in self._goal.clauses)
        if (
            any(type(clause) is not ClauseAssessment for clause in proposal.clauses)
            or tuple(clause.clause_id for clause in proposal.clauses) != expected
        ):
            raise ValueError("Goal estimate must retain the fixed clause identities and order")
        for clause in proposal.clauses:
            self._validate_clause(clause)
        previous = (
            {}
            if self._estimate is None
            else {clause.clause_id: clause for clause in self._estimate.clauses}
        )
        clauses = tuple(
            previous[clause.clause_id]
            if (
                clause.clause_id in PERSISTENT_CLAUSES
                and clause.truth is Truth.UNKNOWN
                and clause.clause_id in previous
                and previous[clause.clause_id].truth is Truth.TRUE
            )
            else clause
            for clause in proposal.clauses
        )
        self._estimate = GoalEstimate(
            self._episode_id,
            self._capture.capture_id,
            self._revision,
            self._goal.sha256,
            self._estimator_id,
            clauses,
        )
        self._accepted = True
        return self._estimate

    def _validate_clause(self, clause):
        if type(clause.truth) is not Truth:
            raise ValueError("Clause truth requires true, false or unknown")
        if type(clause.reason) is not str or not clause.reason.strip():
            raise ValueError("Clause assessment requires an explicit evidence interpretation")
        if type(clause.evidence) is not tuple:
            raise ValueError("Clause evidence requires typed capture references")
        for reference in clause.evidence:
            if type(reference) is not GoalEvidenceReference:
                raise ValueError("Clause evidence requires typed player capture references")
            if (
                any(
                    type(value) is not str
                    for value in (reference.episode_id, reference.capture_id, reference.rgb_sha256)
                )
                or type(reference.ordinal) is not int
                or reference.ordinal < 0
            ):
                raise ValueError("Player capture reference fields have invalid types")
            capture = self._captures.get(reference.capture_id)
            if capture is None or capture.evidence is None or capture.evidence != reference:
                raise ValueError("Clause evidence is unavailable, foreign, stale or forged")
        if clause.truth is not Truth.UNKNOWN and (
            self._capture.evidence is None or self._capture.evidence not in clause.evidence
        ):
            raise ValueError("A known clause requires current granted RGB evidence")
