import json
from pathlib import Path

from factw.env.core.core import AgentObservation, GraphObservation, Observation
from factw.env.core.recording.contract import observation_profile
from factw.env.core.recording.jsonio import asset_path, read_json
from factw.env.core.recording.sensors import (
    SENSOR_NAMES,
    load_sensors,
    save_sensors,
    sensor_paths,
    validate_sensors,
)
from factw.env.core.recording.versions import sensor_encodings as validate_encodings


def validate_observation(observation: Observation | GraphObservation | AgentObservation) -> None:
    if isinstance(observation, GraphObservation):
        GraphObservation(observation.graph, observation.tool_result)
        return
    if isinstance(observation, AgentObservation):
        AgentObservation(observation.text, observation.structured)
        if all(getattr(observation, name) is None for name in SENSOR_NAMES):
            if observation.depth_buffer_encoding is not None:
                raise ValueError("Depth buffer encoding requires a buffer")
            return
    elif not isinstance(observation, Observation):
        raise TypeError("Expected an image, graph or agent observation")
    validate_sensors(
        observation.rgb,
        observation.depth,
        observation.proprioception,
        depth_buffer=observation.depth_buffer,
        depth_buffer_encoding=observation.depth_buffer_encoding,
    )


def observation_paths(
    index: int, observation: Observation | GraphObservation | AgentObservation
) -> dict[str, str]:
    folder = f"observations/{index:06d}"
    if isinstance(observation, GraphObservation):
        return {name: f"{folder}/{name}.json" for name in ("graph", "tool_result")}
    paths = sensor_paths(folder, observation)
    if isinstance(observation, AgentObservation):
        paths["agent"] = f"{folder}/agent.json"
    return paths


def save_observation(
    root: Path, index: int, observation: Observation | GraphObservation | AgentObservation
) -> dict[str, str]:
    validate_observation(observation)
    paths = observation_paths(index, observation)
    payloads = {}
    if isinstance(observation, GraphObservation):
        payloads = {name: getattr(observation, name) for name in ("graph", "tool_result")}
    elif isinstance(observation, AgentObservation):
        payloads = {"agent": {"text": observation.text, "structured": observation.structured}}
    encoded = {
        name: (json.dumps(value, allow_nan=False, ensure_ascii=False) + "\n").encode("utf-8")
        for name, value in payloads.items()
    }
    folder = root / "observations" / f"{index:06d}"
    folder.mkdir(parents=True)
    for name, value in encoded.items():
        (root / paths[name]).write_bytes(value)
    if not isinstance(observation, GraphObservation):
        save_sensors(root, paths, observation)
    return paths


def load_observation(
    root: Path, paths: dict[str, str], *, schema_version="1.0", sensor_encodings=None
) -> Observation | GraphObservation | AgentObservation:
    encodings = validate_encodings(schema_version, sensor_encodings)
    profile = observation_profile(
        root, paths, schema_version=schema_version, sensor_encodings=encodings
    )
    if profile == "graph-tool-v1":
        return GraphObservation(
            **{name: read_json(asset_path(root, path)) for name, path in paths.items()}
        )
    sensors = load_sensors(root, paths)
    if "depth_buffer" in sensors:
        sensors["depth_buffer_encoding"] = encodings["depth_buffer"]
    if profile in {"agent-v1", "agent-v2"}:
        payload = read_json(asset_path(root, paths["agent"]))
        if set(payload) != {"text", "structured"}:
            raise ValueError("Invalid agent observation fields")
        observed = AgentObservation(**payload, **sensors)
    else:
        observed = Observation(**sensors)
    validate_observation(observed)
    return observed
