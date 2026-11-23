"""Explicit native presentation settings and assisted visible-object observations."""

from pathlib import Path

BOOLEAN_OPTIONS = (
    "sound_enabled",
    "render_hud",
    "render_weapon",
    "render_crosshair",
    "render_all_frames",
    "public_labels",
)
OPTIONS = {*BOOLEAN_OPTIONS, "doom_skill", "iwad_path"}


def validate(config):
    for name in BOOLEAN_OPTIONS:
        if name in config and type(config[name]) is not bool:
            raise ValueError(f"{name} must be Boolean")
    if "doom_skill" in config and (
        type(config["doom_skill"]) is not int or not 1 <= config["doom_skill"] <= 5
    ):
        raise ValueError("doom_skill must be an integer from 1 to 5")
    if "iwad_path" in config:
        value = config["iwad_path"]
        if type(value) is not str or not value:
            raise ValueError("iwad_path must name an existing IWAD file")
        path = Path(value).expanduser().resolve(strict=True)
        if not path.is_file():
            raise ValueError("iwad_path must name an existing IWAD file")
        config["iwad_path"] = str(path)


def apply(game, config):
    for name in BOOLEAN_OPTIONS[:-1]:
        if name in config:
            getattr(game, "set_" + name)(config[name])
    if "doom_skill" in config:
        game.set_doom_skill(config["doom_skill"])
    if "iwad_path" in config:
        game.set_doom_game_path(config["iwad_path"])
    game.set_labels_buffer_enabled(config.get("public_labels", False))


def labels(state):
    if state is None:
        return None
    return [
        {
            "id": int(label.object_id),
            "name": label.object_name,
            "category": label.object_category,
            "bbox": [int(getattr(label, key)) for key in ("x", "y", "width", "height")],
            "position": [float(getattr(label, "object_position_" + axis)) for axis in "xyz"],
            "angle": float(label.object_angle),
        }
        for label in state.labels
    ]
