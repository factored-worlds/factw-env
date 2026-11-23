import json
from dataclasses import asdict
from pathlib import Path

import numpy as np
from factw.env.core.recording import Episode, EpisodeWriter
from factw.env.core.recording.inventory import public_files
from factw.env.core.recording.jsonio import json_object, read_json


def collect(path, env, actions, *, engine, engine_version, action_interface, seed=0):
    path = Path(path)
    initial = env.reset(seed=seed)
    path.mkdir(parents=True)
    private = path / "privileged"
    private.mkdir()
    (private / "task.json").write_text(json.dumps(asdict(env.task), indent=2) + "\n")
    with (
        EpisodeWriter(
            path / "episode",
            initial,
            engine_version=engine_version,
            engine=engine,
            action_interface=action_interface,
            seed=seed,
            task_id="game",
            initial_terminated=env.terminated,
        ) as writer,
        (private / "reference.jsonl").open("x", encoding="utf-8") as references,
    ):
        references.write(json.dumps({"step": 0, "reference": env.reference()}) + "\n")
        for action in actions:
            result = env.step(action)
            writer.append(asdict(action), result)
            references.write(
                json.dumps({"step": writer.index, "reference": env.reference()}) + "\n"
            )
    return {
        "episode": str(path / "episode"),
        "steps": writer.index,
        "status": writer.manifest["status"],
    }


def verify(path, *, env_type, task_type, action_type, engine, action_interface):
    path = Path(path)
    episode = Episode(path / "episode")
    if (
        episode.metadata["engine"] != engine
        or episode.metadata["action_interface"] != action_interface
    ):
        raise ValueError("Wrong game trajectory interfaces")
    env = env_type(task_type(**read_json(path / "privileged" / "task.json")))
    env.reset(seed=episode.metadata["seed"])
    with (path / "privileged" / "reference.jsonl").open(encoding="utf-8") as stream:
        annotations = [json_object(line) for line in stream]
    if len(annotations) != episode.metadata["steps"] + 1:
        raise ValueError("Reference count does not match episode")
    if not np.array_equal(env.observe().rgb, episode.initial_observation().rgb):
        raise ValueError("Initial observation does not replay")
    if annotations[0] != {"step": 0, "reference": env.reference()}:
        raise ValueError("Initial reference does not replay")
    for transition in episode.transitions():
        result = env.step(action_type(**transition.action))
        actual = (
            result.reward,
            result.terminated,
            result.truncated,
            result.elapsed_seconds,
            result.outcome,
        )
        saved = transition.result
        expected = (
            saved.reward,
            saved.terminated,
            saved.truncated,
            saved.elapsed_seconds,
            saved.outcome,
        )
        if actual != expected or not np.array_equal(result.observation.rgb, saved.observation.rgb):
            raise ValueError(f"Transition {transition.step} does not replay")
        if annotations[transition.step] != {"step": transition.step, "reference": env.reference()}:
            raise ValueError(f"Reference {transition.step} does not replay")
    status = "terminated" if env.terminated else "truncated" if env.truncated else "partial"
    if episode.metadata["status"] != status:
        raise ValueError("Episode status differs from replayed game")
    return {
        "verified": True,
        "steps": episode.metadata["steps"],
        "public_files": len(public_files(path / "episode")),
    }
