from contextlib import contextmanager
from dataclasses import replace

from factw.env.core.json_values import copy_json
from factw.env.core.recording.contract import text
from factw.env.core.transport import worker
from factw.env.external.catalog import FARAMA_BACKENDS
from factw.env.external.encoding import result

PROTOCOL = "factored-worlds-benchmarks-v3"
BACKENDS = (
    "minigrid",
    "popgym",
    "memory-gym",
    "minihack",
    "textworld",
    "jumanji",
    "craftax",
    "overcooked_v2",
    "libero",
    "robocasa",
    "maniskill",
    "alfworld",
    "scienceworld",
    "appworld",
    "gaia2",
    "tau",
    "browsergym",
    "osworld",
    "behavior",
) + FARAMA_BACKENDS


class BenchmarkEnv:
    def __init__(self, transport, backend: str, parameters: dict, *, max_steps: int):
        if backend not in BACKENDS:
            raise ValueError(f"Unknown benchmark backend: {backend}")
        if type(parameters) is not dict:
            raise ValueError("Benchmark parameters must be a JSON object")
        if type(max_steps) is not int or max_steps < 1:
            raise ValueError("max_steps must be a positive integer")
        self.transport = transport
        self.backend = backend
        self.max_steps = max_steps
        self.steps = 0
        self.terminated = self.truncated = False
        self._active = self._initialized = False
        self._closed = False
        self.metadata = copy_json(
            transport.request("initialize", {"backend": backend, "config": copy_json(parameters)})
        )
        if (
            not {"backend", "versions", "configuration", "snapshot", "replay"}
            <= self.metadata.keys()
        ):
            raise ValueError("Backend metadata is missing required provenance and capabilities")
        text(self.metadata["backend"], "Backend name")
        if self.metadata["backend"] != backend:
            raise ValueError("Worker backend differs from the requested benchmark")
        if (
            type(self.metadata["versions"]) is not dict
            or type(self.metadata["configuration"]) is not dict
        ):
            raise ValueError("Backend versions and configuration must be objects")
        if self.metadata["snapshot"] is not False or self.metadata["replay"] not in (
            "none",
            "seeded-actions",
        ):
            raise ValueError("Unsupported benchmark snapshot/replay capability")
        encodings = self.metadata.setdefault("sensor_encodings", {})
        if type(encodings) is not dict or encodings not in (
            {},
            {"depth_buffer": "vizdoom-depth-u8-v1"},
        ):
            raise ValueError("Invalid benchmark sensor encodings")
        self.metadata["worker_protocol"] = PROTOCOL
        self.metadata["host_max_steps"] = max_steps

    def reset(self, *, seed: int = 0):
        if self._closed:
            raise RuntimeError("Benchmark worker is closed")
        if type(seed) is not int:
            raise ValueError("Seed must be an integer")
        self._active = self._initialized = False
        observed = self._result(self.transport.request("reset", {"seed": seed}))
        if observed.elapsed_seconds != 0:
            raise ValueError("A reset observation must have zero elapsed_seconds")
        self.steps = 0
        self.terminated, self.truncated = observed.terminated, observed.truncated
        self._initialized = True
        self._active = not (self.terminated or self.truncated)
        return observed.observation

    def step(self, action: dict):
        if not self._active or self._closed:
            raise RuntimeError("Reset before stepping an inactive benchmark episode")
        if type(action) is not dict or not action:
            raise ValueError("Benchmark command must be a nonempty JSON object")
        command = copy_json(action)
        self._active = self._initialized = False
        observed = self._result(self.transport.request("step", {"command": command}))
        self._initialized = True
        self.steps += 1
        if self.steps >= self.max_steps and not (observed.terminated or observed.truncated):
            observed = replace(observed, truncated=True, outcome="host_time_limit")
        self.terminated, self.truncated = observed.terminated, observed.truncated
        self._active = not (self.terminated or self.truncated)
        return observed

    def _result(self, payload):
        observed = result(payload)
        encoding = observed.observation.depth_buffer_encoding
        if (
            encoding is not None
            and self.metadata["sensor_encodings"].get("depth_buffer") != encoding
        ):
            raise ValueError("Benchmark depth buffer encoding was not declared")
        return observed

    def reference(self) -> dict:
        self._check_initialized()
        return copy_json(self.transport.request("reference", {}))

    def evaluate(self) -> dict:
        self._check_initialized()
        self._active = False
        return copy_json(self.transport.request("evaluate", {}))

    def _check_initialized(self):
        if self._closed or not self._initialized:
            raise RuntimeError("Reset before inspecting a benchmark episode")

    def snapshot(self):
        raise NotImplementedError("This benchmark adapter does not support physical snapshots")

    def close(self):
        if not self._closed:
            self._closed = True
            self._active = False
            self.transport.request("close", {})


@contextmanager
def connect(command, backend: str, parameters: dict, *, max_steps=1000, timeout=120.0, stderr=None):
    with worker(
        tuple(command),
        timeout=timeout,
        stderr=stderr,
        protocol=PROTOCOL,
        max_message_bytes=32 * 1024 * 1024,
    ) as transport:
        env = BenchmarkEnv(transport, backend, parameters, max_steps=max_steps)
        try:
            yield env
            env.close()
        finally:
            env._closed = True
            env._active = False
