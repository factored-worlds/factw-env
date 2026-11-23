"""Sample and materialize a native key, door and exit mission from an episode seed."""

import hashlib
import json
import tempfile
from pathlib import Path
from random import Random

from .navigation_wad import navigation_wad


def _split_edges(corners, marks):
    """Insert openings and wall panels in clockwise order along their room edges."""
    polygon = []
    for a, b in zip(corners, corners[1:] + corners[:1], strict=True):
        dx, dy = b[0] - a[0], b[1] - a[1]
        points = []
        for x, y in marks:
            distance = (x - a[0]) * dx + (y - a[1]) * dy
            if (x - a[0]) * dy == (y - a[1]) * dx and 0 < distance < dx * dx + dy * dy:
                points.append((distance, (x, y)))
        polygon.extend([a, *(point for _, point in sorted(points))])
    return polygon


def _sample_layout(seed):
    rng = Random(seed)
    heading = rng.randrange(4) * 90
    forward, left = {0: (1, 0), 90: (0, 1), 180: (-1, 0), 270: (0, -1)}[heading]

    def point(x, y):
        return [x * forward - y * left, x * left + y * forward]

    # Construct in door-local coordinates, then rotate all geometry and sensors together.
    width = rng.choice((320, 384, 448, 480))
    height = rng.choice((224, 256, 288, 320))
    door_y = rng.randrange(80, height - 79, 16)
    half_opening = rng.choice((40, 48, 56))
    low, high = door_y - half_opening, door_y + half_opening
    far = width + rng.choice((32, 48, 64))
    end = far + rng.choice((288, 320, 352, 384))
    lower = door_y - rng.randrange(112, 193, 16)
    upper = door_y + rng.randrange(112, 193, 16)
    chamfer = rng.choice((0, 32, 64))
    key_room = [(0, chamfer), (0, height), (width, height), (width, 0)]
    if chamfer:
        key_room.append((chamfer, 0))
    bay_left = rng.choice((32, 48, 64))
    bay_right = bay_left + rng.choice((176, 192, 208))
    bay_depth = rng.choice((96, 112, 128))
    window = [(bay_left, height), (bay_right, height)]
    key_room = _split_edges(key_room, [*window, (width, low), (width, high)])
    door = [(width, low), (width, high), (far, high), (far, low)]
    exit_wall = rng.choice(("opposite", "left", "right"))
    if exit_wall == "opposite":
        offset = rng.randrange(lower + 64, upper - 63, 16)
        panel = [(end, offset - 32), (end, offset + 32)]
        exit_pad = (end - 32, offset)
    else:
        offset = rng.randrange(far + 96, end - 63, 16)
        wall_y = upper if exit_wall == "left" else lower
        panel = [(offset - 32, wall_y), (offset + 32, wall_y)]
        exit_pad = (offset, wall_y - 32 if exit_wall == "left" else wall_y + 32)
    exit_room = _split_edges(
        [(far, lower), (far, upper), (end, upper), (end, lower)],
        [(far, low), (far, high), *panel],
    )
    gallery = [
        window[0],
        (bay_left, height + bay_depth),
        (bay_right, height + bay_depth),
        window[1],
    ]
    sectors = [
        {
            "name": name,
            "tag": tag,
            "polygon": [point(*p) for p in polygon],
            "floor": floor,
            "ceiling": ceiling,
        }
        for name, tag, polygon, floor, ceiling in (
            ("key_room", 1, key_room, 0, 128),
            ("locked_door", 10, door, 0, 0),
            ("exit_room", 2, exit_room, 0, 128),
            ("monster_bay", 3, gallery, 24, 104),
        )
    ]
    sites = [(x, y) for x in range(64, width - 63, 32) for y in range(64, height - 47, 32)]
    start = rng.choice(sites)
    key = rng.choice([p for p in sites if (p[0] - start[0]) ** 2 + (p[1] - start[1]) ** 2 >= 96**2])
    spawn = {
        "id": 0,
        "map": "MAP01",
        "position": point(*start),
        "angle": rng.randrange(8) * 45,
    }
    choices = [bay_left + 48, bay_right - 48]
    enemies = [
        {
            "type": 3002,
            "name": "Demon",
            "position": point(x, height + bay_depth - 40),
            "angle": (heading + 270) % 360,
        }
        for x in rng.sample(choices, rng.randrange(3))
    ]
    center = point((width + far) // 2, door_y)
    scene = {
        "key_position": point(*key),
        "door_approach": point(width - 28, door_y),
        "door_crossing": point(far + 48, door_y),
        "exit_position": point(*exit_pad),
        "door_direction": heading,
    }
    return {
        "sampling_profile": "key-door-exit-layout-v1",
        "seed": seed,
        "sectors": sectors,
        "spawn": spawn,
        "key_position": scene["key_position"],
        "door_center": center,
        "door_direction": heading,
        "door_far_threshold": point(far, door_y),
        "exit_position": scene["exit_position"],
        "exit_wall": exit_wall,
        "exit_panel": [point(*p) for p in panel],
        "enemies": enemies,
        "scene_spec": scene,
    }


def _digest(data):
    return hashlib.sha256(data).hexdigest()


def _json(value):
    return (json.dumps(value, indent=2) + "\n").encode()


def navigation_map_receipt(directory):
    return {
        "path": "scenario_assets/manifest.json",
        "sha256": _digest((Path(directory) / "manifest.json").read_bytes()),
    }


def build_navigation_map(source_dir, destination, seed):
    """Create a self-contained scenario directory usable by both the native player and agent."""
    if type(seed) is not int or not 0 <= seed < 2**31:
        raise ValueError("seed must be an integer from 0 to 2147483647")
    source_dir, destination = Path(source_dir), Path(destination)
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(destination)
    source = json.loads((source_dir / "manifest.json").read_bytes())
    layout = _sample_layout(seed)
    configuration = (source_dir / source["config_file"]).read_bytes()
    behavior = (source_dir / "seeded_task.o").read_bytes()
    for name, data in ((source["config_file"], configuration), ("seeded_task.o", behavior)):
        if _digest(data) != source["assets"][name]:
            raise ValueError(f"Doom scenario asset hash differs: {name}")
    payload = {
        "layout.json": _json(layout),
        source["config_file"]: configuration,
        source["wad_file"]: navigation_wad(layout, behavior),
    }
    manifest = {
        "format_version": 1,
        "config_file": source["config_file"],
        "wad_file": source["wad_file"],
        "scene_spec": layout["scene_spec"],
        "fixtures": [layout["spawn"]],
        "telemetry": source["telemetry"],
        "runtime": source["runtime"],
        "domain": layout,
        "assets": {name: _digest(data) for name, data in payload.items()},
    }
    payload["manifest.json"] = _json(manifest)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=destination.parent) as staging:
        assembled = Path(staging) / "mission"
        assembled.mkdir()
        for name, data in payload.items():
            (assembled / name).write_bytes(data)
        assembled.rename(destination)
    return manifest
