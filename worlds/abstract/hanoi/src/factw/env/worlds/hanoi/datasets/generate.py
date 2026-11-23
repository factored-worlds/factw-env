import json
from pathlib import Path
from random import Random
from uuid import NAMESPACE_URL, uuid5

from factw.env.worlds.hanoi import (
    HanoiState,
    Move,
    apply_move,
    is_legal,
    legal_moves,
    sample_style,
)
from factw.env.worlds.hanoi.datasets.collection import collect_episode
from factw.env.worlds.hanoi.datasets.policy import episode_plan
from factw.env.worlds.hanoi.datasets.splits import internal_moves, split_states


def generate_dataset(
    output: Path,
    seed: int = 0,
    episodes_per_split: tuple[int, int, int] = (128, 32, 32),
    max_steps: int = 16,
    *,
    collection_seed: int | None = None,
    style_seed: int | None = None,
) -> dict:
    for value in (seed, collection_seed, style_seed):
        if value is not None and type(value) is not int:
            raise ValueError("Seeds must be integers")
    if len(episodes_per_split) != 3 or any(
        type(count) is not int or count < 1 for count in episodes_per_split
    ):
        raise ValueError("Supply positive train, validation, and test episode counts")
    if type(max_steps) is not int or max_steps < 5:
        raise ValueError("max_steps must be an integer of at least 5")
    collection_seed = seed if collection_seed is None else collection_seed
    style_seed = seed if style_seed is None else style_seed
    partitions = split_states(seed)
    identity = json.dumps(
        ("hanoi-dataset-v1", seed, collection_seed, style_seed, episodes_per_split, max_steps)
    )
    dataset_id = uuid5(NAMESPACE_URL, identity).hex
    output = Path(output)
    output.mkdir(parents=True)
    (output / "privileged" / "annotations").mkdir(parents=True)
    public = {
        "schema_version": "1.0",
        "engine": "hanoi-symbolic-v1",
        "dataset_id": dataset_id,
        "seed": seed,
        "action_interface": "disk-target-v1",
        "disk_count": 3,
        "max_steps": max_steps,
        "splits": {},
    }
    private = {
        "schema_version": "1.0",
        "collection_seed": collection_seed,
        "style_seed": style_seed,
        "splits": {name: [state.pegs for state in states] for name, states in partitions.items()},
        "episodes": {},
        "coverage": {},
    }
    index = 0
    for (split, states), count in zip(partitions.items(), episodes_per_split, strict=True):
        rng = Random(f"collection:{collection_seed}:{split}")
        starts = list(states)
        rng.shuffle(starts)
        allowed = frozenset(states)
        paths, observed, edges = [], set(), set()
        illegal = 0
        for episode in range(count):
            start = starts[episode % len(starts)]
            task, actions = episode_plan(start, allowed, rng, max_steps, episode // len(starts))
            style_rng = Random(f"style:{style_seed}:{index}")
            style = sample_style(style_rng.randrange(2**63))
            path, details, trajectory = collect_episode(
                output, index, seed, dataset_id, task, style, actions
            )
            paths.append(path)
            private["episodes"][path] = details
            observed.update(trajectory)
            for before, action, after in zip(trajectory[:-1], actions, trajectory[1:], strict=True):
                if is_legal(before, action):
                    edges.add((before, action, after))
                else:
                    illegal += 1
            index += 1
        public["splits"][split] = paths
        private["coverage"][split] = coverage(allowed, observed, edges, illegal)
    write_json(output / "privileged" / "index.json", private)
    write_json(output / "dataset.json", public)
    return public


def coverage(
    allowed: frozenset[HanoiState],
    observed: set[HanoiState],
    edges: set[tuple[HanoiState, Move, HanoiState]],
    illegal_attempts: int,
) -> dict:
    internal = sum(len(internal_moves(state, allowed)) for state in allowed)
    crossing = sum(
        apply_move(state, move) not in allowed for state in allowed for move in legal_moves(state)
    )
    return {
        "assigned_states": len(allowed),
        "observed_states": len(observed),
        "internal_legal_transitions": internal,
        "observed_legal_transitions": len(edges),
        "crossing_legal_transitions_excluded": crossing,
        "moved_disks": sorted({move.disk for _, move, _ in edges}),
        "illegal_attempts": illegal_attempts,
    }


def write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2) + "\n")
