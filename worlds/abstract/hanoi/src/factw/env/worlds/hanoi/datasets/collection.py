import json
from dataclasses import asdict
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from factw.env.core.recording import EpisodeWriter
from factw.env.worlds.hanoi import (
    HanoiEnv,
    HanoiOracle,
    HanoiState,
    HanoiTask,
    Move,
    RenderStyle,
    __version__,
)


def collect_episode(
    root: Path,
    index: int,
    seed: int,
    dataset_id: str,
    task: HanoiTask,
    style: RenderStyle,
    actions: list[Move],
) -> tuple[str, dict, list[HanoiState]]:
    episode_path = f"episodes/{index:06d}"
    annotation_path = f"privileged/annotations/{index:06d}.jsonl"
    episode_id = uuid5(NAMESPACE_URL, f"fw-hanoi:{dataset_id}:episode:{index}").hex
    task_id = uuid5(NAMESPACE_URL, f"fw-hanoi:{dataset_id}:task:{index}").hex
    env = HanoiEnv(task, style=style)
    states = [env.state]
    oracle = HanoiOracle()
    with (
        EpisodeWriter(
            root / episode_path,
            env.reset(seed=seed),
            engine_version=__version__,
            engine="hanoi-symbolic-v1",
            action_interface="disk-target-v1",
            seed=seed,
            task_id=task_id,
            episode_id=episode_id,
        ) as writer,
        (root / annotation_path).open("x") as annotations,
    ):
        annotations.write(json.dumps({"step": 0, "reference": oracle.describe(env.state)}) + "\n")
        for action in actions:
            writer.append(asdict(action), env.step(action))
            states.append(env.state)
            annotations.write(
                json.dumps({"step": writer.index, "reference": oracle.describe(env.state)}) + "\n"
            )
        if not env.terminated:
            raise RuntimeError("Dataset collection did not reach its assigned goal")
    private = {"task": asdict(task), "style": asdict(style), "annotations": annotation_path}
    return episode_path, private, states
