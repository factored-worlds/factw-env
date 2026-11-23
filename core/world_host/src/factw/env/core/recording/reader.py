from collections.abc import Iterator
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path

from factw.env.core.core import (
    AgentObservation,
    GraphObservation,
    Observation,
    StepResult,
)
from factw.env.core.recording import profiles
from factw.env.core.recording.assets import load_observation
from factw.env.core.recording.contract import read_records
from factw.env.core.recording.versions import reject_legacy_depth


@dataclass(frozen=True)
class Transition:
    step: int
    timestamp_seconds: float
    before: Observation | GraphObservation | AgentObservation
    action: dict
    result: StepResult


class Episode:
    def __init__(self, path: str | Path, *, allow_incomplete: bool = False):
        self.path = Path(path)
        self.metadata, self._records = read_records(self.path, allow_incomplete=allow_incomplete)
        reject_legacy_depth(self.metadata, self.metadata["initial_observation"])
        for record in self._records:
            reject_legacy_depth(self.metadata, record["observation"])
            profiles.action(record["action"], self.metadata["action_interface"])

    def _load(self, paths):
        return load_observation(
            self.path,
            paths,
            schema_version=self.metadata["schema_version"],
            sensor_encodings=self.metadata.get("sensor_encodings"),
        )

    def initial_observation(self) -> Observation | GraphObservation | AgentObservation:
        observed = self._load(self.metadata["initial_observation"])
        if self.metadata["engine"] == "review-workflow-v1":
            if not isinstance(observed, GraphObservation):
                raise ValueError("Review workflows require graph/tool observations")
            profiles.review_observation(observed, initial=True)
        return observed

    def transitions(self) -> Iterator[Transition]:
        before = self.initial_observation()
        for record in self._records:
            after = self._load(record["observation"])
            if self.metadata["engine"] == "review-workflow-v1":
                profiles.review_transition(before, record["action"], after, record["outcome"])
            result = StepResult(
                observation=after,
                reward=record["reward"],
                terminated=record["terminated"],
                truncated=record["truncated"],
                elapsed_seconds=record["elapsed_seconds"],
                outcome=record["outcome"],
            )
            next_before = deepcopy(after)
            yield Transition(
                step=record["step"],
                timestamp_seconds=record["timestamp_seconds"],
                before=before,
                action=deepcopy(record["action"]),
                result=result,
            )
            before = next_before
