"""Build the authored mission with pinned ACC source and installed ViZDoom assets."""

import argparse
import hashlib
import json
import struct
import subprocess
from importlib.metadata import version
from pathlib import Path

ACC_REVISION = "e37b18ed84b7aa165b558c8af270fd7d50fc4beb"
HERE = Path(__file__).resolve().parent


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def block(kind, fields):
    contents = "".join(f"    {key} = {json.dumps(value)};\n" for key, value in fields.items())
    return f"{kind}\n{{\n{contents}}}\n"


def textmap(layout, fixture):
    vertices, sides, lines, edges = [], [], [], {}
    for sector_index, sector in enumerate(layout["sectors"]):
        polygon = sector["polygon"]
        for start, end in zip(polygon, polygon[1:] + polygon[:1], strict=True):
            pair = tuple(map(tuple, (start, end)))
            side = dict(
                sector=sector_index,
                texturetop="BIGDOOR2",
                texturebottom="STARTAN3",
                texturemiddle="STARTAN3",
            )
            reverse = edges.get(pair[::-1])
            if reverse is not None:
                line = lines[reverse]
                line.update(sideback=len(sides), twosided=True, blocking=False)
                front = sides[line["sidefront"]]
                front["texturemiddle"] = side["texturemiddle"] = "-"
                names = {sector["name"], layout["sectors"][front["sector"]]["name"]}
                if "blue_door" in names:
                    front["texturetop"] = side["texturetop"] = "DOORBLU"
                    line.update(special=80, arg0=2, playeruse=True, repeatspecial=True)
            else:
                endpoints = []
                for point in (start, end):
                    if point not in vertices:
                        vertices.append(point)
                    endpoints.append(vertices.index(point))
                edges[pair] = len(lines)
                line = dict(v1=endpoints[0], v2=endpoints[1], sidefront=len(sides), blocking=True)
                if start == [1120, 128] and end == [1120, 64]:
                    side["texturemiddle"] = "SW1COMP"
                    line.update(special=80, arg0=3, playeruse=True, repeatspecial=True)
                if start == [1440, 256] and end == [1440, 128]:
                    side["texturemiddle"] = "EXITDOOR"
                lines.append(line)
            sides.append(side)
    result = 'namespace = "ZDoom";\n\n'
    for x, y in vertices:
        result += block("vertex", {"x": float(x), "y": float(y)})
    for sector in layout["sectors"]:
        result += block(
            "sector",
            dict(
                heightfloor=0,
                heightceiling=sector["ceiling"],
                texturefloor=sector["floor"],
                textureceiling="CEIL1_1",
                lightlevel=sector["light"],
                id=sector["tag"],
            ),
        )
    for kind, records in (("sidedef", sides), ("linedef", lines)):
        result += "".join(block(kind, record) for record in records)
    common = dict(
        skill1=True,
        skill2=True,
        skill3=True,
        skill4=True,
        skill5=True,
        single=True,
        dm=False,
        coop=False,
    )
    things = [dict(position=fixture["position"], angle=fixture["angle"], type=1, id=1)]
    for thing in things + layout["things"]:
        result += block(
            "thing",
            dict(
                x=float(thing["position"][0]),
                y=float(thing["position"][1]),
                type=thing["type"],
                id=thing["id"],
                angle=thing.get("angle", 0),
                **common,
            ),
        )
    return result.encode()


def wad(lumps):
    data = bytearray(b"PWAD" + struct.pack("<ii", len(lumps), 0))
    directory = []
    for name, content in lumps:
        directory.append(struct.pack("<ii8s", len(data), len(content), name.encode()))
        data.extend(content)
    struct.pack_into("<i", data, 8, len(data))
    return bytes(data) + b"".join(directory)


def main():
    import vizdoom

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--acc-source", required=True, type=Path)
    source = parser.parse_args().acc_source.resolve()
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=source, text=True).strip()
    if revision != ACC_REVISION:
        raise ValueError(f"ACC source must be {ACC_REVISION}")
    subprocess.run(["git", "diff", "--exit-code", "HEAD"], cwd=source, check=True)
    compiler = source / "acc"
    c_sources = [
        source / f"{name}.c"
        for name in ("acc", "error", "misc", "parse", "pcode", "strlist", "symbol", "token")
    ]
    subprocess.run(["cc", "-O2", "-o", str(compiler), *map(str, c_sources)], check=True)
    layout = json.loads((HERE / "layout.json").read_text())
    fixtures = json.loads((HERE / "fixtures.json").read_text())
    assets = [
        "layout.json",
        "fixtures.json",
        "task.acs",
        "combat_mission.cfg",
        "combat_mission.wad",
        "build.py",
    ]
    maps = HERE / "maps"
    maps.mkdir(exist_ok=True)
    lumps = []
    for fixture in fixtures:
        stem = maps / fixture["map"]
        stem.with_suffix(".acs").write_text(
            f"#define START_HEALTH {fixture['health']}\n"
            f'#define START_AMMO {fixture["ammo"]}\n#include "../task.acs"\n'
        )
        subprocess.run(
            [
                str(compiler),
                "-i",
                str(source),
                str(stem.with_suffix(".acs")),
                str(stem.with_suffix(".o")),
            ],
            check=True,
        )
        content = textmap(layout, fixture)
        stem.with_suffix(".udmf").write_bytes(content)
        lumps.extend(
            [
                (fixture["map"], b""),
                ("TEXTMAP", content),
                ("BEHAVIOR", stem.with_suffix(".o").read_bytes()),
                ("ENDMAP", b""),
            ]
        )
        assets.extend(f"maps/{fixture['map']}.{suffix}" for suffix in ("acs", "o", "udmf"))
    (HERE / "combat_mission.wad").write_bytes(wad(lumps))
    telemetry_names = [
        "has_key",
        "door_open",
        "exited",
        "reactor_active",
        "threats_remaining",
        "near_door",
        "near_reactor",
        "health_available",
        "ammo_available",
        "reserve_health_available",
        "extraction_open",
        "armor_available",
        "region",
    ]
    native = Path(vizdoom.__file__).parent
    manifest = dict(
        format_version=1,
        config_file="combat_mission.cfg",
        wad_file="combat_mission.wad",
        scene_spec=layout["scene_spec"],
        fixtures=fixtures,
        task_instruction="Resupply, defeat both imps, collect the blue key, unlock the blue door, "
        "activate the reactor switch, and reach extraction alive.",
        success_rule="Native exit after both imps have died, BlueCard is held, both physical "
        "doors are passable, the reactor is active, and the player is alive.",
        public_game_variables=[
            "POSITION_X",
            "POSITION_Y",
            "ANGLE",
            "HEALTH",
            "ARMOR",
            "AMMO2",
            "KILLCOUNT",
            "DAMAGE_TAKEN",
            "HITCOUNT",
            *(f"USER{i}" for i in range(1, 14)),
        ],
        worker_options=dict(
            frame_skip=1,
            episode_timeout=7000,
            public_labels=True,
            render_hud=True,
            render_weapon=True,
            render_crosshair=True,
        ),
        telemetry={name: f"USER{index}" for index, name in enumerate(telemetry_names, 1)},
        compiler=dict(project="https://github.com/ZDoom/acc", version="1.60", revision=revision),
        runtime=dict(
            vizdoom_version=version("vizdoom"),
            iwad=dict(name="freedoom2.wad", sha256=sha256(native / "freedoom2.wad")),
            engine_resources=dict(name="vizdoom.pk3", sha256=sha256(native / "vizdoom.pk3")),
        ),
        assets={name: sha256(HERE / name) for name in assets},
    )
    (HERE / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")


if __name__ == "__main__":
    main()
