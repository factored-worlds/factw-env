"""Explicit, local Minari interchange; no environment recovery or network download."""

import argparse
import json
from pathlib import Path

import minari
import numpy as np
from gymnasium import spaces
from minari.data_collector import EpisodeBuffer

from .codecs import decode_action, describe_space, to_json

SCHEMA = "factored-worlds-minari/1"


def restore_space(spec):
    kind = spec["type"]
    if kind == "Dict":
        return spaces.Dict([(key, restore_space(item)) for key, item in spec["spaces"].items()])
    if kind == "Tuple":
        return spaces.Tuple(tuple(restore_space(item) for item in spec["spaces"]))
    if kind == "Discrete":
        return spaces.Discrete(spec["n"], start=spec["start"])
    if kind == "Box":
        if np.dtype(spec["dtype"]).kind not in "iuf":
            raise ValueError("Minari interchange supports numeric Box dtypes")

        def bounds(value):
            if isinstance(value, list):
                return [bounds(item) for item in value]
            return {"+infinity": np.inf, "-infinity": -np.inf}.get(value, value)

        def decoded(value):
            array = np.asarray(bounds(value), dtype=spec["dtype"])
            return array.item() if array.ndim == 0 else array

        return spaces.Box(
            decoded(spec["low"]),
            decoded(spec["high"]),
            shape=tuple(spec["shape"]),
            dtype=spec["dtype"],
        )
    if kind == "MultiDiscrete":
        return spaces.MultiDiscrete(spec["nvec"], start=spec["start"], dtype=spec["dtype"])
    if kind == "MultiBinary":
        return spaces.MultiBinary(tuple(spec["shape"]))
    if kind == "Text":
        return spaces.Text(
            spec["max_length"], min_length=spec["min_length"], charset=spec["charset"]
        )
    raise ValueError(f"Minari interchange does not support {kind} spaces")


def _at(space, values, index):
    if isinstance(space, spaces.Dict):
        return {key: _at(item, values[key], index) for key, item in space.spaces.items()}
    if isinstance(space, spaces.Tuple):
        return [_at(item, values[i], index) for i, item in enumerate(space.spaces)]
    return to_json(values[index])


def _batch(space, values):
    if isinstance(space, spaces.Dict):
        if any(type(value) is not dict or value.keys() != space.spaces.keys() for value in values):
            raise ValueError("Dataset object keys differ from its declared Dict space")
        return {
            key: _batch(item, [value[key] for value in values])
            for key, item in space.spaces.items()
        }
    if isinstance(space, spaces.Tuple):
        if any(type(value) is not list or len(value) != len(space.spaces) for value in values):
            raise ValueError("Dataset tuple length differs from its declared Tuple space")
        return tuple(
            _batch(item, [value[i] for value in values]) for i, item in enumerate(space.spaces)
        )
    validated = [decode_action(space, value) for value in values]
    if isinstance(space, spaces.Text):
        return validated
    return np.asarray(validated, dtype=space.dtype)


def export_dataset(dataset_id, output):
    dataset = minari.load_dataset(dataset_id, download=False)
    observation_space = describe_space(dataset.observation_space)
    action_space = describe_space(dataset.action_space)
    restore_space(observation_space)
    restore_space(action_space)
    episodes = []
    for episode in dataset.iterate_episodes():
        steps = len(episode.rewards)
        if np.asarray(episode.rewards).shape != (steps,):
            raise ValueError("Minari interchange requires scalar rewards")
        metadata = next(iter(dataset.storage.get_episode_metadata([episode.id])))
        episodes.append(
            {
                "id": int(episode.id),
                "seed": to_json(metadata.get("seed")),
                "observations": [
                    _at(dataset.observation_space, episode.observations, i)
                    for i in range(steps + 1)
                ],
                "actions": [_at(dataset.action_space, episode.actions, i) for i in range(steps)],
                "rewards": to_json(episode.rewards),
                "terminations": to_json(episode.terminations),
                "truncations": to_json(episode.truncations),
            }
        )
    value = {
        "schema": SCHEMA,
        "source": dataset_id,
        "observation_space": observation_space,
        "action_space": action_space,
        "infos": "omitted",
        "episodes": episodes,
    }
    with Path(output).open("x", encoding="utf-8") as stream:
        json.dump(value, stream, allow_nan=False)
    return value


def import_dataset(source, dataset_id):
    data = json.loads(Path(source).read_text())
    if data["schema"] != SCHEMA or data["infos"] != "omitted":
        raise ValueError("Expected a public Minari interchange with infos omitted")
    observations, actions = (
        restore_space(data["observation_space"]),
        restore_space(data["action_space"]),
    )
    buffers = []
    for index, episode in enumerate(data["episodes"]):
        if type(episode["id"]) is not int or episode["id"] != index:
            raise ValueError(
                "Preserving Minari episode IDs requires sequential IDs starting at zero"
            )
        if episode["seed"] is not None and (
            type(episode["seed"]) is not int or episode["seed"] < 0
        ):
            raise ValueError("Episode seed must be a nonnegative integer or null")
        count = len(episode["actions"])
        if len(episode["observations"]) != count + 1 or any(
            len(episode[key]) != count for key in ("rewards", "terminations", "truncations")
        ):
            raise ValueError("Episode observation/action/reward lengths disagree")
        if any(
            type(flag) is not bool
            for key in ("terminations", "truncations")
            for flag in episode[key]
        ):
            raise ValueError("Episode boundary flags must be Boolean")
        if any(episode["terminations"][:-1]) or any(episode["truncations"][:-1]):
            raise ValueError("An episode contains steps after a boundary")
        rewards = np.asarray(episode["rewards"])
        if (
            any(type(value) not in (int, float) for value in episode["rewards"])
            or rewards.dtype.kind not in "iuf"
            or rewards.shape != (count,)
            or not np.isfinite(rewards).all()
        ):
            raise ValueError("Minari interchange requires finite scalar rewards")
        buffers.append(
            EpisodeBuffer(
                id=episode["id"],
                seed=episode["seed"],
                observations=_batch(observations, episode["observations"]),
                actions=_batch(actions, episode["actions"]),
                rewards=rewards.tolist(),
                terminations=episode["terminations"],
                truncations=episode["truncations"],
            )
        )
    return minari.create_dataset_from_buffers(
        dataset_id,
        buffers,
        observation_space=observations,
        action_space=actions,
        description=f"Imported from {data['source']}; private infos omitted.",
        jpeg_encoding=False,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="operation", required=True)
    export = commands.add_parser("export")
    export.add_argument("dataset")
    export.add_argument("--output", required=True, type=Path)
    load = commands.add_parser("import")
    load.add_argument("source", type=Path)
    load.add_argument("--dataset", required=True)
    args = parser.parse_args()
    if args.operation == "export":
        report = export_dataset(args.dataset, args.output)
        print(json.dumps({"output": str(args.output), "episodes": len(report["episodes"])}))
    else:
        dataset = import_dataset(args.source, args.dataset)
        print(json.dumps({"dataset": dataset.id, "episodes": dataset.total_episodes}))


if __name__ == "__main__":
    main()
