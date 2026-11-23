import json
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

from factw.env.core.core import (
    AgentObservation,
    GraphObservation,
    Observation,
    StepResult,
)
from factw.env.core.json_values import copy_json
from factw.env.core.recording import profiles
from factw.env.core.recording.assets import (
    observation_paths,
    save_observation,
    validate_observation,
)
from factw.env.core.recording.contract import metadata, number, transition
from factw.env.core.recording.versions import boundary_status, reject_legacy_depth


class EpisodeWriter:
    def __init__(
        self,
        path: str | Path,
        initial: Observation | GraphObservation | AgentObservation,
        *,
        engine: str,
        engine_version: str,
        action_interface: str,
        seed: int,
        task_id: str,
        initial_terminated: bool = False,
        episode_id: str | None = None,
        schema_version: str = "1.0",
        sensor_encodings: dict | None = None,
        scenario_id: str | None = None,
        scenario_revision: int | None = None,
    ):
        validate_observation(initial)
        if type(initial_terminated) is not bool:
            raise ValueError("Initial termination must be Boolean")
        if schema_version == "1.0" and sensor_encodings is not None:
            raise ValueError("Sensor encoding declarations require trajectory 2.0")
        if engine == "review-workflow-v1":
            if not isinstance(initial, GraphObservation) or action_interface != "review-command-v1":
                raise ValueError("Review workflows require graph observations and review commands")
            profiles.review_observation(initial, initial=True)
        self._before = deepcopy(initial)
        self.path = Path(path)
        self.index = 0
        self.time = 0.0
        self.ended = initial_terminated
        self.manifest = {
            "schema_version": schema_version,
            "episode_id": uuid4().hex if episode_id is None else episode_id,
            "engine": engine,
            "engine_version": engine_version,
            "action_interface": action_interface,
            "seed": seed,
            "task_id": task_id,
            "initial_observation": observation_paths(0, initial),
            "status": "terminated" if initial_terminated else "recording",
            "steps": 0,
            "duration_seconds": 0.0,
        }
        if schema_version == "2.0":
            self.manifest["sensor_encodings"] = copy_json(sensor_encodings)
        if scenario_id is not None or scenario_revision is not None:
            self.manifest.update(scenario_id=scenario_id, scenario_revision=scenario_revision)
        self._profile = metadata(self.path, self.manifest, allow_incomplete=True)
        self._schema_version = schema_version
        self._sensor_encodings = deepcopy(self.manifest.get("sensor_encodings"))
        self._scenario = (scenario_id, scenario_revision)
        reject_legacy_depth(self.manifest, self.manifest["initial_observation"])
        self.path.mkdir(parents=True)
        save_observation(self.path, 0, initial)
        self._stream = (self.path / "steps.jsonl").open("x", encoding="utf-8")
        self._write_manifest()

    def append(self, action: dict, result: StepResult) -> None:
        if self._stream.closed or self.ended:
            raise RuntimeError("Cannot append after the writer closed or episode ended")
        self._validate_format()
        if type(result.observation) is not type(self._before):
            raise TypeError("An episode cannot change observation modality")
        validate_observation(result.observation)
        number(result.elapsed_seconds, "Elapsed time", nonnegative=True)
        record = {
            "step": self.index + 1,
            "timestamp_seconds": self.time + result.elapsed_seconds,
            "elapsed_seconds": result.elapsed_seconds,
            "action": copy_json(action),
            "observation": observation_paths(self.index + 1, result.observation),
            "reward": result.reward,
            "terminated": result.terminated,
            "truncated": result.truncated,
            "outcome": result.outcome,
        }
        next_time = transition(
            self.path,
            record,
            self.index + 1,
            self.time,
            self._profile,
            schema_version=self.manifest["schema_version"],
            sensor_encodings=self.manifest.get("sensor_encodings"),
        )
        reject_legacy_depth(self.manifest, record["observation"])
        profiles.action(action, self.manifest["action_interface"])
        if self.manifest["engine"] == "review-workflow-v1":
            profiles.review_transition(self._before, action, result.observation, result.outcome)
        encoded = json.dumps(record, allow_nan=False)
        save_observation(self.path, self.index + 1, result.observation)
        self._stream.write(encoded + "\n")
        self.index += 1
        self.time = next_time
        self._before = deepcopy(result.observation)
        self.ended = result.terminated or result.truncated
        self.manifest["status"] = boundary_status(result.terminated, result.truncated)

    def _write_manifest(self) -> None:
        self._validate_format()
        self.manifest.update(steps=self.index, duration_seconds=self.time)
        (self.path / "episode.json").write_text(
            json.dumps(self.manifest, indent=2) + "\n", encoding="utf-8"
        )

    def _validate_format(self) -> None:
        if (
            self.manifest.get("schema_version") != self._schema_version
            or self.manifest.get("sensor_encodings") != self._sensor_encodings
            or (self.manifest.get("scenario_id"), self.manifest.get("scenario_revision"))
            != self._scenario
        ):
            raise ValueError(
                "Trajectory schema, sensor encodings and scenario identity are fixed at creation"
            )

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self._stream.close()
        if exc_type is not None:
            self.manifest["status"] = "interrupted"
        elif self.manifest["status"] == "recording":
            self.manifest["status"] = "partial"
        self._write_manifest()
