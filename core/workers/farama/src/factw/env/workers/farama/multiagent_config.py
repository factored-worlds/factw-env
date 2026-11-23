"""Construction and public visibility of PettingZoo-family environments."""

import re
from importlib import import_module

from factw.env.workers.farama.objectives import RewardProjection

SUITES = {
    "pettingzoo": ("pettingzoo.", "pettingzoo.classic.tictactoe_v3"),
    "mpe2": ("mpe2.", "mpe2.simple_spread_v3"),
    "magent2": ("magent2.environments.", "magent2.environments.battle_v4"),
    "momaland": ("momaland.envs.", "momaland.envs.item_gathering.moitem_gathering_v0"),
}


def configuration(config: dict, suite: str) -> tuple[dict, RewardProjection]:
    if suite not in SUITES:
        raise ValueError(f"Unsupported multi-agent suite: {suite}")
    if not isinstance(config, dict):
        raise ValueError("Multi-agent configuration must be an object")
    unknown = config.keys() - {
        "env_id",
        "api",
        "env_kwargs",
        "observation_policy",
        "public_info_keys",
        "reward_projection",
    }
    if unknown:
        raise ValueError(f"Unknown multi-agent configuration: {sorted(unknown)}")
    prefix, default = SUITES[suite]
    result = {
        "env_id": config.get("env_id", default),
        "api": config.get("api", "aec"),
        "env_kwargs": config.get("env_kwargs", {}),
        "public_info_keys": config.get("public_info_keys", ["action_mask"]),
        "observation_policy": config.get("observation_policy", "selected_agent"),
        "reward_projection": config.get("reward_projection"),
    }
    name = result["env_id"]
    if (
        not isinstance(name, str)
        or not name.startswith(prefix)
        or not re.fullmatch(r"[a-zA-Z][a-zA-Z0-9_]*(\.[a-zA-Z][a-zA-Z0-9_]*)+", name)
    ):
        raise ValueError(f"env_id must be an upstream module under {prefix}")
    if result["api"] not in {"aec", "parallel"}:
        raise ValueError("api must be aec or parallel")
    policy = "selected_agent" if result["api"] == "aec" else "joint_agent_observations"
    if result["observation_policy"] != policy:
        raise ValueError(f"{result['api']} requires observation_policy={policy}")
    if not isinstance(result["env_kwargs"], dict):
        raise ValueError("env_kwargs must be an object")
    if result["env_kwargs"].get("render_mode") is not None:
        raise ValueError("Multi-agent rendering is evaluator-only; render_mode must be null")
    keys = result["public_info_keys"]
    if not isinstance(keys, list) or any(not isinstance(key, str) for key in keys):
        raise ValueError("public_info_keys must be a list of strings")
    projection = RewardProjection(
        result["reward_projection"], multiagent=True, multiobjective=suite == "momaland"
    )
    result["reward_projection"] = projection.config
    return result, projection


def create_environment(config: dict):
    module = import_module(config["env_id"])
    factory = "env" if config["api"] == "aec" else "parallel_env"
    return getattr(module, factory)(**config["env_kwargs"])
