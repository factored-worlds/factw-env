"""Hashed scenario selection and loaded-runtime identity checks."""

import hashlib
from contextlib import contextmanager
from importlib.resources import as_file, files
from pathlib import Path

from factw.env.core.recording.jsonio import read_json

PRESENTATION_OPTIONS = frozenset(
    (
        "sound_enabled",
        "render_hud",
        "render_weapon",
        "render_crosshair",
        "render_all_frames",
        "resolution",
        "doom_skill",
    )
)


SCENARIOS = {
    "games.doom/eliminate-single-target": "Eliminate a target with a reference-assisted baseline.",
    "games.doom/retrieve-key-and-escape": "Collect the key, unlock the door and escape.",
    "games.doom/activate-reactor-and-extract": "Resupply, fight, activate the reactor and extract.",
}

_SCENARIO_FOLDERS = {
    "games.doom/eliminate-single-target": "eliminate_single_target",
    "games.doom/retrieve-key-and-escape": "retrieve_key_and_escape",
    "games.doom/activate-reactor-and-extract": "activate_reactor_and_extract",
}


def scenario_resources(scenario):
    if scenario not in _SCENARIO_FOLDERS:
        raise ValueError(f"Unknown Doom scenario: {scenario}")
    return files("factw.env.worlds.doom").joinpath("scenarios", _SCENARIO_FOLDERS[scenario])


def scenario_identity(scenario):
    descriptor = read_json(scenario_resources(scenario).joinpath("scenario.json"))
    revision = descriptor["behavior_revision"]
    if descriptor["scenario_id"] != scenario or type(revision) is not int or revision < 1:
        raise ValueError("Installed scenario identity or behavior revision is invalid")
    return {"scenario_id": scenario, "scenario_revision": revision}


def document_bytes(scenario):
    return {
        source.name: source.read_bytes()
        for source in sorted(
            scenario_resources(scenario).joinpath("smsl").iterdir(), key=lambda p: p.name
        )
        if source.name.endswith(".smsl")
    }


def document_sources(scenario):
    return {name: data.decode("utf-8") for name, data in document_bytes(scenario).items()}


@contextmanager
def scenario_directory(scenario):
    """Keep the complete installed native asset directory alive for its consumer."""
    assets = scenario_resources(scenario).joinpath("assets")
    if not assets.is_dir():
        raise ValueError(f"Doom scenario uses a native preset, without authored assets: {scenario}")
    with as_file(assets) as directory:
        yield directory


def default_scene_spec(scenario):
    with scenario_directory(scenario) as directory:
        _, manifest = scenario_configuration(directory)
        return manifest["scene_spec"]


def presentation_options(options):
    options = {} if options is None else dict(options)
    if unexpected := options.keys() - PRESENTATION_OPTIONS:
        raise ValueError(f"Unsupported Doom presentation options: {sorted(unexpected)}")
    return options


def scenario_configuration(scenario_dir, *, start=0, visible=False, presentation=None):
    presentation = presentation_options(presentation)
    scenario_dir = Path(scenario_dir).resolve(strict=True)
    manifest = read_json(scenario_dir / "manifest.json")
    if manifest["format_version"] != 1:
        raise ValueError("Unsupported Doom scenario manifest")
    fixtures = manifest["fixtures"]
    if type(start) is not int or not 0 <= start < len(fixtures):
        raise ValueError(f"start must select one of {len(fixtures)} declared fixtures")
    fixture = fixtures[start]
    if fixture["id"] != start:
        raise ValueError("Doom fixture IDs must match their declared indices")
    for key in ("config_file", "wad_file"):
        if manifest[key] not in manifest["assets"]:
            raise ValueError(f"Scenario {key} must have a declared asset hash")
    for name, expected in manifest["assets"].items():
        asset = (scenario_dir / name).resolve(strict=True)
        if not asset.is_relative_to(scenario_dir):
            raise ValueError("Scenario assets must remain inside their declared directory")
        if hashlib.sha256(asset.read_bytes()).hexdigest() != expected:
            raise ValueError(f"Doom scenario asset hash differs: {name}")
    config = {
        "config_path": str(scenario_dir / manifest["config_file"]),
        "doom_map": fixture["map"],
        "frame_skip": 4,
        "episode_timeout": 3000,
        "public_game_variables": [
            "POSITION_X",
            "POSITION_Y",
            "ANGLE",
            "HEALTH",
            *manifest.get("public_game_variables", []),
            *manifest["telemetry"].values(),
        ],
        "visible": visible,
    }
    config["public_game_variables"] = list(dict.fromkeys(config["public_game_variables"]))
    options = manifest.get("worker_options", {})
    if unexpected := options.keys() - (
        PRESENTATION_OPTIONS | {"frame_skip", "episode_timeout", "public_labels"}
    ):
        raise ValueError(f"Unsupported Doom scenario worker options: {sorted(unexpected)}")
    config.update(options)
    config.update(presentation)
    return config, manifest


def validate_runtime(metadata, manifest):
    if metadata["versions"]["vizdoom"] != manifest["runtime"]["vizdoom_version"]:
        raise ValueError("Doom runtime version differs from the scenario manifest")
    expected = {key: manifest["runtime"][key] for key in ("iwad", "engine_resources")}
    for name, key in (("configuration", "config_file"), ("scenario", "wad_file")):
        filename = manifest[key]
        expected[name] = {"name": Path(filename).name, "sha256": manifest["assets"][filename]}
    if metadata["assets"] != expected:
        raise ValueError("Loaded Doom assets differ from the scenario manifest")
