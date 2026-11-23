from importlib.metadata import version
from math import isfinite

import numpy as np

from .codecs import decode_action, describe_space, to_json
from .suites import DEFAULTS, make_environment
from .types import Observation, Transition


class GymnasiumBackend:
    def __init__(self, config: dict, suite="gymnasium"):
        allowed = {
            "env_id",
            "env_kwargs",
            "observation",
            "public_info_keys",
            "reference_info_keys",
            "success_info_key",
            "step_seconds",
        }
        if unknown := config.keys() - allowed:
            raise ValueError(f"Unknown {suite} configuration: {sorted(unknown)}")
        default_id, _, distribution, success_key = DEFAULTS[suite]
        self.suite, self.distribution = suite, distribution
        self.config = {
            "env_id": default_id,
            "env_kwargs": {},
            "observation": "native",
            "public_info_keys": [],
            "reference_info_keys": [],
            "success_info_key": success_key,
            "step_seconds": 0.0,
            **config,
        }
        if type(self.config["env_id"]) is not str or not self.config["env_id"]:
            raise ValueError("env_id must be a nonempty string")
        if type(self.config["env_kwargs"]) is not dict:
            raise ValueError("env_kwargs must be an object")
        if self.config["observation"] not in {"native", "rgb", "native-rgb"}:
            raise ValueError("observation must be native, rgb, or native-rgb")
        for key in ("public_info_keys", "reference_info_keys"):
            if type(self.config[key]) is not list or any(
                type(item) is not str for item in self.config[key]
            ):
                raise ValueError(f"{key} must be a list of strings")
        if self.config["success_info_key"] is not None and not isinstance(
            self.config["success_info_key"], str
        ):
            raise ValueError("success_info_key must be a string or null")
        duration = self.config["step_seconds"]
        if type(duration) not in (float, int) or not isfinite(duration) or duration < 0:
            raise ValueError("step_seconds must be finite and nonnegative")
        kwargs = dict(self.config["env_kwargs"])
        if "render_mode" in kwargs:
            raise ValueError("Select rendering with observation, not env_kwargs.render_mode")
        if self.config["observation"] in {"rgb", "native-rgb"} and suite != "miniwob":
            kwargs["render_mode"] = "rgb_array"
        else:
            kwargs["render_mode"] = None
        if suite == "metaworld":
            kwargs.setdefault("env_name", "reach-v3")
            kwargs.setdefault("seed", 0)
        self.env = make_environment(suite, self.config["env_id"], kwargs)
        self.config["env_kwargs"] = {k: v for k, v in kwargs.items() if k != "render_mode"}
        self.step_count = 0
        self.total_reward = 0.0
        self.last_native_reward = None
        self.terminated = self.truncated = False
        self.initialized = False
        self.last_observation = None
        self.last_info = {}
        self.success = None

    def reset(self, seed: int) -> Transition:
        native, info = self.env.reset(seed=seed)
        self.env.action_space.seed(seed)
        self.step_count, self.total_reward = 0, 0.0
        self.terminated = self.truncated = False
        self.initialized = True
        self.last_native_reward = None
        self.last_observation, self.last_info = native, info
        self.success = self._success(info)
        return Transition(self._observation(native))

    def _reward(self, native_reward):
        reward = float(native_reward)
        if not isfinite(reward):
            raise ValueError("Upstream reward must be finite")
        return reward

    def step(self, command: dict) -> Transition:
        if not self.initialized or self.terminated or self.truncated:
            raise RuntimeError("Reset before stepping an inactive episode")
        if command.keys() != {"action"}:
            raise ValueError("Command must contain exactly action")
        action = decode_action(self.env.action_space, command["action"])
        native, native_reward, terminated, truncated, info = self.env.step(action)
        reward = self._reward(native_reward)
        self.step_count += 1
        self.total_reward += reward
        self.terminated, self.truncated = bool(terminated), bool(truncated)
        self.last_observation, self.last_info = native, info
        self.success = self._success(info)
        outcome = "running"
        if terminated:
            outcome = (
                "terminated" if self.success is None else ("success" if self.success else "failure")
            )
        elif truncated:
            outcome = "truncated"
        return Transition(
            self._observation(native),
            reward,
            bool(terminated),
            bool(truncated),
            outcome,
            float(self.config["step_seconds"]),
        )

    def _success(self, info):
        key = self.config["success_info_key"]
        if key is None or key not in info:
            return None
        value = to_json(info[key])
        if type(value) not in (bool, int, float) or value not in (0, 1):
            raise ValueError("Success info must be a Boolean or zero/one scalar")
        return bool(value)

    def _observation(self, native):
        profile = self.config["observation"]
        structured = {
            "info": {
                key: to_json(self.last_info[key])
                for key in self.config["public_info_keys"]
                if key in self.last_info
            },
            "episode_flags": {"terminated": self.terminated, "truncated": self.truncated},
        }
        if profile in {"native", "native-rgb"}:
            structured["observation"] = to_json(native)
        if self.last_native_reward is not None:
            structured["native_reward"] = to_json(self.last_native_reward)
        rgb = None
        if profile in {"rgb", "native-rgb"}:
            rgb = native["screenshot"] if self.suite == "miniwob" else self.env.render()
            if (
                not isinstance(rgb, np.ndarray)
                or rgb.dtype != np.uint8
                or (rgb.ndim != 3 or rgb.shape[2] != 3)
            ):
                raise ValueError("rgb_array rendering must return an H×W×3 uint8 image")
            rgb = rgb.copy()
        return Observation(structured=structured, rgb=rgb)

    def metadata(self):
        return {
            "backend": self.suite,
            "versions": {name: version(name) for name in {self.distribution, "gymnasium", "numpy"}},
            "configuration": self.config,
            "action_space": describe_space(self.env.action_space),
            "observation_space": describe_space(self.env.observation_space),
            "snapshot": False,
            "replay": "none" if self.suite == "miniwob" else "seeded-actions",
            "replay_notes": "reproducibility depends on upstream environment",
            "reward_semantics": "unmodified upstream per-step scalar reward",
            "success_semantics": "configured info key; null means upstream success unavailable",
            "time_semantics": "configured seconds per step; zero means unspecified",
            "boundary_semantics": "independent native termination and truncation flags",
        }

    def reference(self):
        return {
            "step_count": self.step_count,
            "info": {
                key: to_json(self.last_info[key])
                for key in self.config["reference_info_keys"]
                if key in self.last_info
            },
        }

    def evaluate(self):
        return {
            "return": self.total_reward,
            "steps": self.step_count,
            "success": self.success,
            "terminated": self.terminated,
            "truncated": self.truncated,
        }

    def close(self):
        self.env.close()
