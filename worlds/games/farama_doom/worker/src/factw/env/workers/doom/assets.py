from hashlib import sha256
from pathlib import Path


def asset(path):
    value = Path(path).resolve(strict=True)
    return {"name": value.name, "sha256": sha256(value.read_bytes()).hexdigest()}


def provenance(game, config_path):
    import vizdoom

    package = Path(vizdoom.__file__).parent
    result = {
        "configuration": asset(config_path),
        "iwad": asset(game.get_doom_game_path()),
        "engine_resources": asset(package / "vizdoom.pk3"),
    }
    if scenario := game.get_doom_scenario_path():
        result["scenario"] = asset(scenario)
    return result
