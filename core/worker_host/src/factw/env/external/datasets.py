"""Convert explicit Minari exchanges without importing a simulator runtime."""

import json
from pathlib import Path

from factw.env.core.core import AgentObservation, StepResult
from factw.env.core.recording import Episode, EpisodeWriter
from factw.env.core.recording.contract import number
from factw.env.core.recording.jsonio import read_json

from . import __version__

SCHEMA = "factored-worlds-minari/1"


def import_minari(source, output):
    data = read_json(Path(source))
    if data["schema"] != SCHEMA or data["infos"] != "omitted":
        raise ValueError("Expected a public Minari interchange with infos omitted")
    episode_ids = set()
    for episode in data["episodes"]:
        count = len(episode["actions"])
        if len(episode["observations"]) != count + 1 or any(
            len(episode[key]) != count for key in ("rewards", "terminations", "truncations")
        ):
            raise ValueError("Episode observation/action/reward lengths disagree")
        if type(episode["id"]) is not int or episode["id"] < 0:
            raise ValueError("Episode ID must be a nonnegative integer")
        if episode["id"] in episode_ids:
            raise ValueError("Episode IDs must be unique")
        episode_ids.add(episode["id"])
        if episode["seed"] is not None and (
            type(episode["seed"]) is not int or episode["seed"] < 0
        ):
            raise ValueError("Episode seed must be a nonnegative integer or null")
        for reward in episode["rewards"]:
            number(reward, "Dataset reward")
        if any(
            type(flag) is not bool
            for key in ("terminations", "truncations")
            for flag in episode[key]
        ):
            raise ValueError("Episode boundary flags must be Boolean")
        if any(episode["terminations"][:-1]) or any(episode["truncations"][:-1]):
            raise ValueError("An episode contains steps after a boundary")
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    paths = []

    def observe(value, flags=None):
        structured = {"observation": value}
        if flags is not None:
            structured["episode_flags"] = flags
        return AgentObservation(structured=structured)

    for index, episode in enumerate(data["episodes"]):
        path = output / f"episode-{index:06d}"
        with EpisodeWriter(
            path,
            observe(episode["observations"][0]),
            engine="benchmark-minari-v1",
            engine_version=__version__,
            action_interface="benchmark-command-v1",
            seed=0 if episode["seed"] is None else episode["seed"],
            task_id=data["source"],
            schema_version="2.0",
            sensor_encodings={},
        ) as writer:
            writer.manifest["minari"] = {
                "source": data["source"],
                "episode_id": episode["id"],
                "seed": episode["seed"],
                "observation_space": data["observation_space"],
                "action_space": data["action_space"],
                "infos": "omitted",
                "elapsed_seconds": "unavailable; recorded as zero",
                "boundary_policy": "independent native termination and truncation flags",
            }
            for i, action in enumerate(episode["actions"]):
                terminated, truncated = episode["terminations"][i], episode["truncations"][i]
                writer.append(
                    {"command": {"action": action}},
                    StepResult(
                        observe(
                            episode["observations"][i + 1],
                            {"terminated": terminated, "truncated": truncated},
                        ),
                        episode["rewards"][i],
                        terminated,
                        truncated,
                        0.0,
                        "dataset_step",
                    ),
                )
        paths.append(str(path))
    return paths


def export_minari(episodes, output):
    result = None
    for source in episodes:
        episode = Episode(source)
        metadata = episode.metadata.get("minari")
        if metadata is None:
            raise ValueError("Export requires imported Minari episodes with explicit native spaces")
        header = {
            "schema": SCHEMA,
            **{
                key: metadata[key]
                for key in ("source", "observation_space", "action_space", "infos")
            },
        }
        if result is None:
            result = {**header, "episodes": []}
        elif any(result[key] != value for key, value in header.items()):
            raise ValueError("Minari episodes must have matching spaces and dataset provenance")
        rows = list(episode.transitions())
        observations = [episode.initial_observation()] + [row.result.observation for row in rows]
        native_flags = [row.result.observation.structured["episode_flags"] for row in rows]
        for row, flags in zip(rows, native_flags, strict=True):
            if (
                flags.keys() != {"terminated", "truncated"}
                or any(type(value) is not bool for value in flags.values())
                or row.result.terminated != flags["terminated"]
                or row.result.truncated
                != (
                    flags["truncated"]
                    if episode.metadata["schema_version"] == "2.0"
                    else flags["truncated"] and not flags["terminated"]
                )
            ):
                raise ValueError("Native Minari flags disagree with the recorded boundary")
        result["episodes"].append(
            {
                "id": metadata["episode_id"],
                "seed": metadata["seed"],
                "observations": [item.structured["observation"] for item in observations],
                "actions": [row.action["command"]["action"] for row in rows],
                "rewards": [row.result.reward for row in rows],
                "terminations": [flags["terminated"] for flags in native_flags],
                "truncations": [flags["truncated"] for flags in native_flags],
            }
        )
    if result is None:
        raise ValueError("Supply at least one episode")
    with Path(output).open("x", encoding="utf-8") as stream:
        json.dump(result, stream, allow_nan=False)
    return str(output)
