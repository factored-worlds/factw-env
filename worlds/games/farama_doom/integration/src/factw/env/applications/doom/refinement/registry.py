"""Host-owned implementations and information capabilities, never proposal code."""

from dataclasses import dataclass

from ..bindings.button_primitives import ButtonCommand


def _text(value):
    if type(value) is not str or not value.strip():
        raise ValueError("A registered implementation requires explicit identifiers and meaning")


@dataclass(frozen=True)
class GroundingBinding:
    identifier: str
    revision: str
    meaning: str
    input_stream_ids: tuple[str, ...]
    evaluate: object
    goal_clause_id: str | None = None

    def __post_init__(self):
        for value in (self.identifier, self.revision, self.meaning):
            _text(value)
        if type(self.input_stream_ids) is not tuple or not self.input_stream_ids:
            raise ValueError("Grounding requires an explicit tuple of granted input streams")
        for value in self.input_stream_ids:
            _text(value)
        if len(set(self.input_stream_ids)) != len(self.input_stream_ids):
            raise ValueError("Grounding input streams must be unique")
        if not callable(self.evaluate):
            raise ValueError("Grounding requires a host-registered callable")
        if self.goal_clause_id is not None:
            _text(self.goal_clause_id)

    def describe(self):
        return {
            "identifier": self.identifier,
            "revision": self.revision,
            "meaning": self.meaning,
            "input_stream_ids": list(self.input_stream_ids),
            "goal_clause_id": self.goal_clause_id,
        }


@dataclass(frozen=True)
class PrimitiveBinding:
    identifier: str
    revision: str
    contract_id: str
    command: ButtonCommand

    def __post_init__(self):
        for value in (self.identifier, self.revision, self.contract_id):
            _text(value)
        if type(self.command) is not ButtonCommand:
            raise ValueError("Primitive registrations require a validated ButtonCommand")

    def describe(self):
        return {
            "identifier": self.identifier,
            "revision": self.revision,
            "contract_id": self.contract_id,
            "command": self.command.as_dict(),
        }


@dataclass(frozen=True)
class RefinementRegistry:
    groundings: tuple[GroundingBinding, ...] = ()
    primitives: tuple[PrimitiveBinding, ...] = ()
    observable_goal_clauses: tuple[str, ...] = ()
    observation_condition: str = "rgb_only"

    def __post_init__(self):
        for records, kind in (
            (self.groundings, GroundingBinding),
            (self.primitives, PrimitiveBinding),
        ):
            if type(records) is not tuple or any(type(record) is not kind for record in records):
                raise ValueError("Registries require immutable typed implementation tuples")
            if len({record.identifier for record in records}) != len(records):
                raise ValueError("Registered implementation identifiers must be unique")
        _text(self.observation_condition)
        if type(self.observable_goal_clauses) is not tuple:
            raise ValueError("Observable goal clauses require an explicit tuple")
        for clause in self.observable_goal_clauses:
            _text(clause)
        if len(set(self.observable_goal_clauses)) != len(self.observable_goal_clauses):
            raise ValueError("Observable goal clauses must be unique")
        if (
            self.observation_condition == "rgb_only"
            and "native_exit_completed" in self.observable_goal_clauses
        ):
            raise ValueError("Current RGB-only observation cannot grant native-exit evidence")

    def grounding(self, identifier):
        return self._find(self.groundings, identifier, "grounding")

    def primitive(self, identifier):
        return self._find(self.primitives, identifier, "primitive")

    @staticmethod
    def _find(records, identifier, label):
        result = next((item for item in records if item.identifier == identifier), None)
        if result is None:
            raise ValueError(f"Unknown host-registered {label}: {identifier}")
        return result

    def describe(self):
        return {
            "groundings": [item.describe() for item in self.groundings],
            "primitives": [item.describe() for item in self.primitives],
            "observable_goal_clauses": list(self.observable_goal_clauses),
            "observation_condition": self.observation_condition,
        }
