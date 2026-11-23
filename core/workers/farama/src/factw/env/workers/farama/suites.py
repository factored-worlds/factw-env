from importlib import import_module

import gymnasium as gym

DEFAULTS = {
    "gymnasium": ("Taxi-v4", None, "gymnasium", None),
    "gymnasium-robotics": (
        "FetchReach-v4",
        "gymnasium_robotics",
        "gymnasium-robotics",
        "is_success",
    ),
    "metaworld": ("Meta-World/MT1", "metaworld", "metaworld", "success"),
    "highway": ("highway-v0", "highway_env", "highway-env", "is_success"),
    "miniwob": ("miniwob/click-test-v1", "miniwob", "miniwob", None),
    "ale": ("ALE/Pong-v5", "ale_py", "ale-py", None),
    "stable-retro": ("Airstriker-Genesis-v0", "stable_retro", "stable-retro", None),
    "shimmy": ("dm_control/cartpole-swingup-v0", "shimmy", "shimmy", None),
    "mo-gymnasium": ("deep-sea-treasure-v0", "mo_gymnasium", "mo-gymnasium", None),
}


def make_environment(suite, env_id, kwargs):
    _, module_name, _, _ = DEFAULTS[suite]
    module = import_module(module_name) if module_name else None
    if suite == "stable-retro":
        return module.make(game=env_id, **kwargs)
    if suite == "mo-gymnasium":
        return module.make(env_id, **kwargs)
    if module is not None:
        gym.register_envs(module)
    return gym.make(env_id, **kwargs)
