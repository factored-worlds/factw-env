"""Project reviewed observation estimates through declared State Language writers."""

import hashlib
from dataclasses import dataclass

import smsl

from ..contracts.goal_estimation import Truth
from ..contracts.model_grounding import GeneratedPredicate
from ..information.player_observation.refinement_grounding import ModelGroundingBoundary
from ..refinement.boolean_proof import BooleanClosure
from ..refinement.documents import LinkedDocuments
from ..refinement.inputs import GrantedRequest, validate_candidate_bytes
from ..refinement.registry import GroundingBinding


@dataclass(frozen=True)
class ObservationWriter:
    document: str
    instance: str
    event: str
    fields: tuple[tuple[str, str | None], ...]
    unknown: bool


def _unknown(value):
    return value == {"kind": "literal", "value": {"kind": "unknown"}}


class RefinementObservations:
    """Derive meaning, targets and event payloads from one reviewed candidate.

    The executable profile admits singleton Boolean closures, not guesses about
    individual conjuncts. Unknown facts need an explicit external reset event.
    """

    def __init__(
        self, request, candidate_bytes, *, estimator_id, grounding_revision, public_priors=()
    ):
        if type(request) is not GrantedRequest:
            raise ValueError("Observation composition requires the granted request")
        candidate = validate_candidate_bytes(candidate_bytes, request)
        self._candidate_sha256 = hashlib.sha256(candidate_bytes).hexdigest()
        self._request_sha256 = request.sha256
        documents = LinkedDocuments(candidate)
        closure = BooleanClosure(documents)
        goal_clauses = {
            item["grounding_id"]: item["goal_clause_id"]
            for item in candidate["goal_correspondence"]
            if item["grounding_id"] is not None
        }
        predicates, facts, records = [], {}, {}
        for item in candidate["grounding"]:
            dependencies = closure.predicate(item["predicate"])
            if len(dependencies) != 1:
                raise ValueError(
                    "Observation projection requires one independently grounded Boolean fact; "
                    "aggregate conjunctions cannot identify their false constituents"
                )
            fact = next(iter(dependencies))
            if fact in facts:
                raise ValueError("Observation groundings cannot duplicate the same base fact")
            facts[fact] = item["id"]
            records[item["id"]] = item
            predicates.append(
                GeneratedPredicate(
                    item["id"],
                    item["meaning"],
                    item["predicate"]["document_id"],
                    item["predicate"]["address"],
                    goal_clauses.get(item["id"]),
                )
            )
        self._predicates = tuple(predicates)
        self._boundary = ModelGroundingBoundary(
            candidate_sha256=self._candidate_sha256,
            predicates=self._predicates,
            estimator_id=estimator_id,
            grounding_revision=grounding_revision,
            public_priors=public_priors,
        )
        self._writers = self._writers_for(documents, facts)
        self._bindings = tuple(
            GroundingBinding(
                records[predicate.identifier]["binding_id"],
                self.boundary.revision_sha256,
                predicate.meaning,
                tuple(records[predicate.identifier]["input_stream_ids"]),
                lambda name=predicate.identifier: self.boundary.assessment(name),
                predicate.goal_clause_id,
            )
            for predicate in self._predicates
            if records[predicate.identifier]["binding_id"] is not None
        )
        self._bound_predicates = tuple(
            predicate.identifier
            for predicate in self._predicates
            if records[predicate.identifier]["binding_id"] is not None
        )

    @property
    def candidate_sha256(self):
        return self._candidate_sha256

    @property
    def boundary(self):
        return self._boundary

    @property
    def request_sha256(self):
        return self._request_sha256

    @property
    def predicates(self):
        return self._predicates

    @property
    def bindings(self):
        return self._bindings

    @staticmethod
    def _writers_for(documents, facts):
        instances = {document: instance for instance, document in documents.instances.items()}
        grouped, supported = {}, {fact: set() for fact in facts}
        events_used = set()
        for document, branch, field in facts:
            definition = next(
                item for item in documents.canonical[document]["branches"] if item["name"] == branch
            )
            for reaction in definition["reactions"]:
                if any(update["field"] == field for update in reaction["updates"]):
                    events_used.add((document, reaction["event"]))
        for document, event in sorted(events_used):
            key = document, event
            entries, modes = [], set()
            for branch in documents.canonical[document]["branches"]:
                if branch["states"] or branch.get("operations"):
                    raise ValueError(
                        "Observation event projection excludes state lifecycle and operations"
                    )
                for reaction in branch["reactions"]:
                    if reaction["event"] != event:
                        continue
                    if (
                        reaction["guard"] is not None
                        or reaction["target"] is not None
                        or reaction["emit"]
                    ):
                        raise ValueError("Observation events cannot guard, transition or emit")
                    for update in reaction["updates"]:
                        fact = document, branch["name"], update["field"]
                        if fact not in facts:
                            raise ValueError("Observation events cannot update ungrounded facts")
                        value = update["value"]
                        unknown = _unknown(value)
                        if not unknown and not (
                            value.get("kind") == "read" and value.get("source") == "payload"
                        ):
                            raise ValueError(
                                "Observation writers require payload reads or unknown resets"
                            )
                        modes.add(unknown)
                        entries.append((facts[fact], None if unknown else value["field"]))
                        supported[fact].add(unknown)
            if len(modes) != 1:
                raise ValueError("An observation event cannot mix known writes and unknown resets")
            unknown = modes.pop()
            schema = next(
                item for item in documents.canonical[document]["events"] if item["name"] == event
            )
            fields = {item["name"]: item for item in schema["fields"]}
            payload_fields = {field for _, field in entries if field is not None}
            if set(fields) != payload_fields or any(
                item["type"] != "bool" or item["nullable"] for item in fields.values()
            ):
                raise ValueError(
                    "Observation payloads require exactly their nonnullable Boolean fields"
                )
            if event in {"command_applied", "command_failed"}:
                raise ValueError("Command outcomes cannot be observation writers")
            grouped[key] = ObservationWriter(
                document, instances[document], event, tuple(entries), unknown
            )
        if any(modes != {False, True} for modes in supported.values()):
            raise ValueError(
                "Each observation fact needs a payload writer and an explicit unknown reset"
            )
        return tuple(grouped.values())

    def events(self, execution, estimate, *, time):
        if estimate is not self.boundary.current_estimate:
            raise ValueError("Projection requires the exact current accepted predicate estimate")
        if (
            estimate is None
            or execution.episode_id != estimate.episode_id
            or execution.latest_capture_id != estimate.capture_id
        ):
            raise ValueError("Projection requires the current execution episode and capture")
        if type(time) is not int or not 0 <= time < 2**64:
            raise ValueError("Observation time requires an unsigned integer")
        current = {item.predicate_id: item for item in estimate.assessments}
        if any(
            binding.evaluate() is not current[identifier]
            for identifier, binding in zip(self._bound_predicates, self._bindings, strict=True)
        ):
            raise ValueError("Grounding callbacks must return their current accepted assessments")
        clauses = {item.clause_id: item for item in estimate.goal_estimate.clauses}
        truths = {item.predicate_id: item.truth for item in estimate.assessments}
        for predicate in self.predicates:
            if predicate.goal_clause_id is not None:
                truths[predicate.identifier] = clauses[predicate.goal_clause_id].truth
        planned, covered = [], set()
        for writer in self._writers:
            selected = [
                (identifier, field)
                for identifier, field in writer.fields
                if (truths[identifier] is Truth.UNKNOWN) == writer.unknown
            ]
            if not selected:
                continue
            if len(selected) != len(writer.fields):
                raise ValueError(
                    "A shared observation event cannot project mixed known and unknown facts"
                )
            payload = {}
            for identifier, field in selected:
                covered.add(identifier)
                if field is None:
                    continue
                value = truths[identifier] is Truth.TRUE
                if field in payload and payload[field] != value:
                    raise ValueError(
                        "A shared payload field cannot represent conflicting predicate estimates"
                    )
                payload[field] = value
            planned.append(
                (
                    writer.instance,
                    smsl.Event(
                        writer.event, time, execution.context(writer.instance), payload=payload
                    ),
                )
            )
        if covered != set(truths):
            raise ValueError("Every current predicate needs an exact observation projection")
        return tuple(planned)

    def apply(self, execution, estimate, *, time):
        events = self.events(execution, estimate, time=time)
        execution.validate_observation_time(time, tuple(instance for instance, _ in events))
        return tuple(execution.observe(instance, event) for instance, event in events)
