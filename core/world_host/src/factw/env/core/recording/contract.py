from math import isclose, isfinite
from pathlib import Path

from factw.env.core.recording.domain_actions import ENGINE_INTERFACES
from factw.env.core.recording.jsonio import asset_path, json_object, read_json
from factw.env.core.recording.versions import (
    boundary_status,
)
from factw.env.core.recording.versions import (
    schema_version as validate_version,
)
from factw.env.core.recording.versions import (
    sensor_encodings as validate_encodings,
)

COMPLETE = {"partial", "terminated", "truncated", "terminated_and_truncated"}
INCOMPLETE = {"recording", "interrupted"}
TIME_REL_TOL = 1e-9
TIME_ABS_TOL = 1e-12


def text(value, name: str) -> None:
    if type(value) is not str or not value:
        raise ValueError(f"{name} must be a nonempty string")
    value.encode("utf-8")


def number(value, name: str, *, nonnegative: bool = False) -> None:
    if type(value) not in (int, float) or not isfinite(value):
        raise ValueError(f"{name} must be a finite number")
    if nonnegative and value < 0:
        raise ValueError(f"{name} must be nonnegative")


def close(left: float, right: float) -> bool:
    return isclose(left, right, rel_tol=TIME_REL_TOL, abs_tol=TIME_ABS_TOL)


def observation_profile(
    root: Path, paths: dict, *, schema_version="1.0", sensor_encodings=None
) -> str:
    encodings = validate_encodings(schema_version, sensor_encodings)
    if type(paths) is not dict:
        raise ValueError("Observation asset paths must be an object")
    for path in paths.values():
        asset_path(root, path)
    keys = set(paths)
    sensors = {"rgb", "depth", "proprioception"}
    suffix = "v1"
    if schema_version == "2.0":
        sensors.add("depth_buffer")
        suffix = "v2"
        if "depth_buffer" in keys and "depth_buffer" not in encodings:
            raise ValueError("Depth buffer requires its declared sensor encoding")
    if "agent" in keys and keys <= {"agent", *sensors}:
        if keys & (sensors - {"rgb"}) and "rgb" not in keys:
            raise ValueError("Agent sensors require RGB")
        return "agent-" + suffix
    if keys == {"graph", "tool_result"}:
        return "graph-tool-v1"
    if "rgb" in keys and keys <= sensors:
        return "image-" + suffix
    raise ValueError("Invalid observation asset profile")


def metadata(root: Path, value: dict, *, allow_incomplete: bool = False) -> str:
    required = {
        "schema_version",
        "episode_id",
        "engine",
        "action_interface",
        "initial_observation",
        "status",
        "steps",
        "duration_seconds",
    }
    if type(value) is not dict or not required <= value.keys():
        raise ValueError("Missing required trajectory metadata")
    version = validate_version(value["schema_version"])
    encodings = validate_encodings(version, value.get("sensor_encodings"))
    for name in ("episode_id", "engine", "action_interface"):
        text(value[name], name)
    for name in ("engine_version", "task_id"):
        if name in value:
            text(value[name], name)
    if "scenario_id" in value or "scenario_revision" in value:
        text(value.get("scenario_id"), "Scenario ID")
        if type(value.get("scenario_revision")) is not int or value["scenario_revision"] < 1:
            raise ValueError("Scenario behavior revision must be a positive integer")
    if "seed" in value and type(value["seed"]) is not int:
        raise ValueError("Seed must be an integer")
    if type(value["steps"]) is not int or value["steps"] < 0:
        raise ValueError("Episode steps must be a nonnegative integer")
    number(value["duration_seconds"], "Episode duration", nonnegative=True)
    text(value["status"], "Status")
    complete = COMPLETE if version == "2.0" else COMPLETE - {"terminated_and_truncated"}
    if value["status"] not in complete | INCOMPLETE:
        raise ValueError("Unknown episode status")
    if not allow_incomplete and value["status"] not in complete:
        raise ValueError("Episode recording is incomplete")
    profile = observation_profile(
        root, value["initial_observation"], schema_version=version, sensor_encodings=encodings
    )
    if value["engine"].startswith("benchmark-") and (
        profile not in {"agent-v1", "agent-v2"}
        or value["action_interface"] != "benchmark-command-v1"
    ):
        raise ValueError("Benchmark engines require agent observations and benchmark commands")
    if value["engine"] == "review-workflow-v1" and (
        profile != "graph-tool-v1" or value["action_interface"] != "review-command-v1"
    ):
        raise ValueError("Review workflows require graph observations and review commands")
    if value["engine"] in ENGINE_INTERFACES and (
        profile not in {"image-v1", "image-v2"}
        or value["action_interface"] != ENGINE_INTERFACES[value["engine"]]
    ):
        raise ValueError("Domain engine requires its named action interface and image observations")
    return profile


def transition(
    root: Path,
    value: dict,
    index: int,
    time: float,
    profile: str,
    *,
    schema_version="1.0",
    sensor_encodings=None,
) -> float:
    required = {
        "step",
        "timestamp_seconds",
        "elapsed_seconds",
        "action",
        "observation",
        "reward",
        "terminated",
        "truncated",
        "outcome",
    }
    if type(value) is not dict or not required <= value.keys():
        raise ValueError("Missing required transition fields")
    if type(value["step"]) is not int or value["step"] != index:
        raise ValueError("Episode transition indices are not consecutive")
    if type(value["action"]) is not dict:
        raise ValueError("Transition action must be a JSON object")
    text(value["outcome"], "Outcome")
    number(value["reward"], "Reward")
    number(value["elapsed_seconds"], "Elapsed time", nonnegative=True)
    number(value["timestamp_seconds"], "Timestamp", nonnegative=True)
    total = time + value["elapsed_seconds"]
    if not isfinite(total):
        raise ValueError("Episode time must remain finite")
    if not close(value["timestamp_seconds"], total):
        raise ValueError("Timestamp does not match cumulative elapsed time")
    if type(value["terminated"]) is not bool or type(value["truncated"]) is not bool:
        raise ValueError("Episode boundaries must be Boolean")
    if schema_version == "1.0" and value["terminated"] and value["truncated"]:
        raise ValueError("A transition cannot both terminate and truncate")
    if (
        observation_profile(
            root,
            value["observation"],
            schema_version=schema_version,
            sensor_encodings=sensor_encodings,
        )
        != profile
    ):
        raise ValueError("An episode cannot change observation modality")
    return total


def read_records(path: Path, *, allow_incomplete: bool = False) -> tuple[dict, tuple[dict, ...]]:
    meta = read_json(asset_path(path, "episode.json"))
    profile = metadata(path, meta, allow_incomplete=allow_incomplete)
    rows = []
    time = 0.0
    ended = False
    with asset_path(path, "steps.jsonl").open(encoding="utf-8") as stream:
        for index, line in enumerate(stream, start=1):
            if ended:
                raise ValueError("Episode contains a transition after its boundary")
            row = json_object(line)
            time = transition(
                path,
                row,
                index,
                time,
                profile,
                schema_version=meta["schema_version"],
                sensor_encodings=meta.get("sensor_encodings"),
            )
            ended = row["terminated"] or row["truncated"]
            rows.append(row)
    if len(rows) != meta["steps"]:
        raise ValueError("Episode transition count does not match its manifest")
    if not close(time, meta["duration_seconds"]):
        raise ValueError("Episode duration does not match its transitions")
    if meta["status"] in COMPLETE:
        status = "partial"
        if rows:
            status = boundary_status(rows[-1]["terminated"], rows[-1]["truncated"])
        elif meta["status"] == "terminated":
            status = "terminated"
        if status != meta["status"]:
            raise ValueError("Episode status does not match its final boundary")
    return meta, tuple(rows)
