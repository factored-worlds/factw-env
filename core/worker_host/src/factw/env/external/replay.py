import numpy as np
from factw.env.core.recording import Episode
from factw.env.external.env import connect


def same_observation(left, right):
    if left.text != right.text or left.structured != right.structured:
        raise ValueError("Benchmark replay observation differs")
    if left.depth_buffer_encoding != right.depth_buffer_encoding:
        raise ValueError("Benchmark replay depth buffer encoding differs")
    for name in ("rgb", "depth", "proprioception", "depth_buffer"):
        before, after = getattr(left, name), getattr(right, name)
        if (before is None) != (after is None):
            raise ValueError(f"Benchmark replay {name} availability differs")
        if before is not None and (
            before.dtype != after.dtype or not np.array_equal(before, after)
        ):
            raise ValueError(f"Benchmark replay {name} differs")


def verify(path, command, backend, parameters, *, timeout=120.0, stderr=None):
    episode = Episode(path)
    meta = episode.metadata
    if meta["engine"] != f"benchmark-{backend}-v1":
        raise ValueError("Recorded benchmark backend differs")
    recorded = meta["benchmark"]
    if recorded["replay"] != "seeded-actions":
        raise ValueError("This backend does not declare verified seeded replay")
    with connect(
        command,
        backend,
        parameters,
        max_steps=recorded["host_max_steps"],
        timeout=timeout,
        stderr=stderr,
    ) as env:
        if env.metadata != recorded:
            raise ValueError("Benchmark replay configuration or runtime provenance differs")
        same_observation(env.reset(seed=meta["seed"]), episode.initial_observation())
        if meta["steps"] == 0 and (
            env.terminated != (meta["status"] == "terminated") or env.truncated
        ):
            raise ValueError("Benchmark replay initial boundary differs")
        count = 0
        for row in episode.transitions():
            result = env.step(row.action["command"])
            same_observation(result.observation, row.result.observation)
            if (
                result.reward,
                result.terminated,
                result.truncated,
                result.outcome,
                result.elapsed_seconds,
            ) != (
                row.result.reward,
                row.result.terminated,
                row.result.truncated,
                row.result.outcome,
                row.result.elapsed_seconds,
            ):
                raise ValueError("Benchmark replay transition differs")
            count += 1
    return {"steps": count, "public_observations_exact": True, "provenance_exact": True}
