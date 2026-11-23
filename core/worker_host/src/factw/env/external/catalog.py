"""Upstream families and their independently installed workers."""

FARAMA_BACKENDS = (
    "gymnasium",
    "gymnasium-robotics",
    "metaworld",
    "highway",
    "vizdoom",
    "miniwob",
    "ale",
    "stable-retro",
    "shimmy",
    "pettingzoo",
    "mpe2",
    "magent2",
    "mo-gymnasium",
    "momaland",
)

UNAVAILABLE = {
    "miniworld": "Upstream deprecated; no maintained integration is advertised.",
    "microrts-py": "Upstream deprecated; no maintained integration is advertised.",
    "procgen2": "Upstream rewrite has no supported runtime profile here.",
}


def catalog():
    return {
        "worker": "factw.env.workers.farama",
        "backends": list(FARAMA_BACKENDS),
        "existing": {"minigrid": "MiniGrid and BabyAI use the existing external worker."},
        "tools": {"minari": "Offline dataset interchange; fw-minari, not a live backend."},
        "unavailable": dict(UNAVAILABLE),
        "acceptance": "Verify task success with the selected environment's evaluation criteria.",
    }
