"""Run one reviewed generated composition over fresh, granted player captures."""

from dataclasses import asdict, dataclass
from hashlib import sha256
from math import isfinite
from time import monotonic
from uuid import uuid4

import smsl

from ..contracts.goal_estimation import Truth
from ..information.player_observation import PlayerObservation
from ..refinement.admission import CandidateAdmission, CandidateReview
from ..refinement.boolean_proof import BooleanClosure
from ..refinement.documents import LinkedDocuments
from .refinement_observations import RefinementObservations


def _limit(value, maximum, label):
    if type(value) is not int or not 1 <= value <= maximum:
        raise ValueError(f"{label} must be between 1 and {maximum}")
    return value


@dataclass(frozen=True)
class ParentCondition:
    refinement_id: str
    block: str
    state: str
    postcondition: Truth


@dataclass(frozen=True)
class RefinementResult:
    stop_reason: str
    episode_id: str | None
    closure_sha256: str
    candidate_sha256: str
    cycles: int
    dispatches: int
    goal_estimate: object
    generated_goal: Truth
    parent_conditions: tuple[ParentCondition, ...]
    trace: tuple[dict, ...]

    @property
    def complete(self):
        return (
            self.stop_reason == "goal_satisfied"
            and self.goal_estimate is not None
            and self.goal_estimate.complete
            and self.generated_goal is Truth.TRUE
            and all(
                item.state != "success" or item.postcondition is Truth.TRUE
                for item in self.parent_conditions
            )
        )

    def as_dict(self):
        return {**asdict(self), "complete": self.complete}


class RefinementSession:
    """The host owns effects and capture; estimators receive only projected input."""

    def __init__(
        self,
        admission,
        review,
        *,
        reviewed_closure,
        environment,
        observations,
        capture,
        estimator=None,
        clock=monotonic,
        max_cycles=500,
        max_wall_seconds=1200,
    ):
        if type(admission) is not CandidateAdmission or type(review) is not CandidateReview:
            raise ValueError("A refinement run requires its actual candidate admission and review")
        if not review.ready or reviewed_closure != review.closure_sha256:
            raise ValueError("A refinement run requires the complete ready reviewed closure")
        if type(observations) is not RefinementObservations:
            raise ValueError("A refinement run requires its admitted observation grounding")
        self._candidate_sha = sha256(review._source).hexdigest()
        if (
            observations.candidate_sha256 != self._candidate_sha
            or observations.request_sha256 != admission.request_sha256
        ):
            raise ValueError("Observation grounding must belong to the exact reviewed candidate")
        if any(
            admission.registry.grounding(item.identifier) is not item
            for item in observations.bindings
        ):
            raise ValueError("Admission must retain the exact observation grounding callbacks")
        if any(not callable(item) for item in (capture, clock)) or (
            estimator is not None and not callable(getattr(estimator, "estimate", None))
        ):
            raise ValueError("A refinement run requires explicit capture, clock and estimator")
        if (
            type(max_wall_seconds) not in (int, float)
            or not isfinite(max_wall_seconds)
            or not 0 < max_wall_seconds <= 1200
        ):
            raise ValueError("max_wall_seconds must be positive and at most 1200")
        self._max_cycles = _limit(max_cycles, 500, "max_cycles")
        self._max_wall_seconds = max_wall_seconds
        self._admission, self._review = admission, review
        self._closure = reviewed_closure
        self._environment, self._observations = environment, observations
        self._estimator, self._capture, self._clock = estimator, capture, clock
        self._documents = LinkedDocuments(review.candidate)
        self._proof = BooleanClosure(self._documents)
        self._instances = {document: name for name, document in self._documents.instances.items()}
        self._goal = self._proof.predicate(review.candidate["entrypoints"]["goal"])
        self._parents = tuple(
            (
                item["id"],
                self._documents.execution_block(item["refined_execution"])["block_id"],
                self._proof.condition(item["parent_postcondition"]),
            )
            for item in review.candidate["action_refinements"]
        )
        self._execution = None
        self._episode = self._observations.boundary.start_episode()
        self._started = self._stopped = False
        self._cycles = 0
        self._trace = []
        self._last_clock = None
        self._projected_capture = None

    @property
    def execution(self):
        return self._execution

    @property
    def episode_id(self):
        return self._episode

    def stop(self):
        self._stopped = True

    def _elapsed(self, started):
        now = self._clock()
        if (
            type(now) not in (int, float)
            or not isfinite(now)
            or now < started
            or (self._last_clock is not None and now < self._last_clock)
        ):
            raise ValueError("The run clock must provide finite monotonic seconds")
        self._last_clock = now
        return now - started

    def _refresh(self):
        self._projected_capture = None
        capture = self._capture()
        if capture is None:
            capture_id = f"missing_{uuid4().hex}"
            self._observations.boundary.missing_capture(capture_id)
            self._execution.missing_capture(capture_id)
            return False
        if type(capture) is not PlayerObservation:
            raise ValueError("Host capture must return only PlayerObservation or None")
        self._observations.boundary.capture(capture)
        self._execution.capture(capture)
        return True

    def _truth(self, facts):
        values = tuple(
            self._execution.facts(self._instances[document], branch)[field]
            for document, branch, field in facts
        )
        if any(value is False for value in values):
            return Truth.FALSE
        if any(value is smsl.UNKNOWN for value in values):
            return Truth.UNKNOWN
        if any(value is not True for value in values):
            raise ValueError("An admitted Boolean observation has a non-Boolean runtime value")
        return Truth.TRUE

    def _conditions(self):
        states = self._execution.inspect()["states"]
        return tuple(
            ParentCondition(identifier, block, states[block], self._truth(facts))
            for identifier, block, facts in self._parents
        )

    def _result(self, reason):
        estimate = None if self._execution is None else self._observations.boundary.current_estimate
        projected = estimate is not None and self._projected_capture == estimate.capture_id
        parents = () if self._execution is None else self._conditions()
        if not projected:
            parents = tuple(
                ParentCondition(item.refinement_id, item.block, item.state, Truth.UNKNOWN)
                for item in parents
            )
        return RefinementResult(
            reason,
            self._episode,
            self._closure,
            self._candidate_sha,
            self._cycles,
            0 if self._execution is None else self._execution.dispatch_count,
            None if estimate is None else estimate.goal_estimate,
            self._truth(self._goal) if projected else Truth.UNKNOWN,
            parents,
            tuple(self._trace),
        )

    def run(self, estimator=None):
        if self._started:
            raise ValueError(
                "A refinement session runs once; start a fresh host and native episode"
            )
        self._started = True
        if self._stopped:
            return self._result("stop_requested")
        if estimator is not None:
            if self._estimator is not None:
                raise ValueError("Configure exactly one observation estimator")
            self._estimator = estimator
        if not callable(getattr(self._estimator, "estimate", None)):
            raise ValueError("Configure an observation estimator before running")
        started = self._clock()
        if type(started) not in (int, float) or not isfinite(started):
            raise ValueError("The run clock must provide finite monotonic seconds")
        self._last_clock = started
        self._execution = self._admission.activate(
            self._review,
            reviewed_closure=self._closure,
            environment=self._environment,
            episode_id=self._episode,
        )
        try:
            available = self._refresh()
            while True:
                if self._stopped:
                    return self._result("stop_requested")
                if self._elapsed(started) >= self._max_wall_seconds:
                    return self._result("wall_budget")
                if self._cycles >= self._max_cycles:
                    return self._result("decision_budget")
                self._cycles += 1
                estimate = self._observations.boundary.estimate(self._estimator)
                if self._elapsed(started) >= self._max_wall_seconds:
                    return self._result("wall_budget")
                if self._stopped:
                    return self._result("stop_requested")
                time = self._cycles * 2
                self._observations.apply(self._execution, estimate, time=time)
                self._projected_capture = estimate.capture_id
                if not available:
                    return self._result("observation_unavailable")
                if (
                    self._admission.active is not self._execution
                    or self._admission.active_closure != self._closure
                ):
                    raise ValueError("The active reviewed composition changed during execution")
                report, tickets = self._execution.tick(
                    {instance: time for instance in self._instances.values()}
                )
                parents = self._conditions()
                record = {
                    "cycle": self._cycles,
                    "capture_id": estimate.capture_id,
                    "goal_estimate": estimate.goal_estimate.as_dict(),
                    "predicate_estimate": asdict(estimate),
                    "execution": report,
                    "parent_conditions": [asdict(item) for item in parents],
                    "generated_goal": self._truth(self._goal).value,
                    "admissions": [asdict(item) for item in tickets],
                    "receipt": None,
                }
                self._trace.append(record)
                unconfirmed = [
                    item
                    for item in parents
                    if item.state == "success" and item.postcondition is not Truth.TRUE
                ]
                if unconfirmed:
                    return self._result("parent_postcondition_unconfirmed")
                if estimate.goal_estimate.complete and self._truth(self._goal) is Truth.TRUE:
                    return self._result("goal_satisfied")
                if self._environment.terminated or self._environment.truncated:
                    return self._result("episode_ended")
                if report["status"] == "success":
                    return self._result(
                        "goal_false" if self._truth(self._goal) is Truth.FALSE else "goal_unknown"
                    )
                if report["status"] == "failure":
                    return self._result("execution_failure")
                if tickets:
                    if self._elapsed(started) >= self._max_wall_seconds:
                        return self._result("wall_budget")
                    if self._stopped:
                        return self._result("stop_requested")
                    receipt = self._execution.dispatch(tickets[0], time=time + 1)
                    record["receipt"] = {
                        "command_status": receipt.command_status,
                        "admission": asdict(receipt.admission),
                        "command": receipt.command,
                    }
                available = self._refresh()
        finally:
            self._execution.cancel_pending()
