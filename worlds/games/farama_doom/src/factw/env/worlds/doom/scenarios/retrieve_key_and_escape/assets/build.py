"""Build deterministic UDMF maps and ACS bytecode with pinned ACC source."""

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
    return (
        kind
        + "\n{\n"
        + "".join(f"    {key} = {json.dumps(value)};\n" for key, value in fields.items())
        + "}\n"
    )


def textmap(layout, fixture):
    vertices, sides, lines, edges = [], [], [], {}
    for sector_index, sector in enumerate(layout["sectors"]):
        polygon = sector["polygon"]
        for start, end in zip(polygon, polygon[1:] + polygon[:1], strict=True):
            pair = tuple(map(tuple, (start, end)))
            side = {
                "sector": sector_index,
                "texturetop": "BIGDOOR2",
                "texturebottom": "STARTAN3",
                "texturemiddle": "STARTAN3",
            }
            if start == [768, 160] and end == [768, 96]:
                side["texturemiddle"] = "EXITDOOR"
            reverse = edges.get(pair[::-1])
            if reverse is not None:
                line = lines[reverse]
                line["sideback"] = len(sides)
                line["twosided"] = True
                line["blocking"] = False
                sides[line["sidefront"]]["texturemiddle"] = "-"
                sides[line["sidefront"]]["texturetop"] = "DOORBLU"
                side["texturemiddle"] = "-"
                side["texturetop"] = "DOORBLU"
                line.update(special=80, arg0=2, playeruse=True, repeatspecial=True)
            else:
                endpoints = []
                for point in (start, end):
                    if point not in vertices:
                        vertices.append(point)
                    endpoints.append(vertices.index(point))
                edges[pair] = len(lines)
                lines.append(
                    {
                        "v1": endpoints[0],
                        "v2": endpoints[1],
                        "sidefront": len(sides),
                        "blocking": True,
                    }
                )
            sides.append(side)
    result = 'namespace = "ZDoom";\n\n'
    for x, y in vertices:
        result += block("vertex", {"x": float(x), "y": float(y)})
    for sector in layout["sectors"]:
        result += block(
            "sector",
            {
                "heightfloor": 0,
                "heightceiling": sector["ceiling"],
                "texturefloor": "FLOOR0_1",
                "textureceiling": "CEIL1_1",
                "lightlevel": 224,
                "id": sector["tag"],
            },
        )
    for kind, records in (("sidedef", sides), ("linedef", lines)):
        for record in records:
            result += block(kind, record)
    common = {
        "skill1": True,
        "skill2": True,
        "skill3": True,
        "skill4": True,
        "skill5": True,
        "single": True,
        "dm": False,
        "coop": False,
    }
    result += block(
        "thing",
        {
            "x": float(fixture["position"][0]),
            "y": float(fixture["position"][1]),
            "type": 1,
            "angle": fixture["angle"],
            **common,
        },
    )
    result += block(
        "thing", {"x": float(layout["key"][0]), "y": float(layout["key"][1]), "type": 5, **common}
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
    parser.add_argument(
        "--acc-source",
        required=True,
        type=Path,
        help="checkout of ZDoom/acc at the pinned ACC 1.60 revision",
    )
    args = parser.parse_args()
    source = args.acc_source.resolve()
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
    behavior = HERE / "task.o"
    for script in ("task", "seeded_task"):
        subprocess.run(
            [
                str(compiler),
                "-i",
                str(source),
                str(HERE / f"{script}.acs"),
                str(HERE / f"{script}.o"),
            ],
            check=True,
        )
    layout = json.loads((HERE / "layout.json").read_text())
    fixtures = json.loads((HERE / "fixtures.json").read_text())
    lumps = []
    maps = HERE / "maps"
    maps.mkdir(exist_ok=True)
    for fixture in fixtures:
        content = textmap(layout, fixture)
        (maps / f"{fixture['map']}.udmf").write_bytes(content)
        lumps.extend(
            [
                (fixture["map"], b""),
                ("TEXTMAP", content),
                ("BEHAVIOR", behavior.read_bytes()),
                ("ENDMAP", b""),
            ]
        )
    (HERE / "key_door_exit.wad").write_bytes(wad(lumps))
    assets = [
        "layout.json",
        "fixtures.json",
        "task.acs",
        "task.o",
        "seeded_task.acs",
        "seeded_task.o",
        "key_door_exit.cfg",
        "key_door_exit.wad",
        "build.py",
    ]
    assets += [f"maps/{fixture['map']}.udmf" for fixture in fixtures]
    manifest = {
        "format_version": 1,
        "config_file": "key_door_exit.cfg",
        "wad_file": "key_door_exit.wad",
        "scene_spec": layout["scene_spec"],
        "fixtures": fixtures,
        "telemetry": {
            "has_key": "USER1",
            "door_open": "USER2",
            "exited": "USER3",
            "near_door": "USER4",
            "region": "USER5",
        },
        "compiler": {
            "project": "https://github.com/ZDoom/acc",
            "version": "1.60",
            "revision": ACC_REVISION,
        },
        "runtime": {
            "vizdoom_version": version("vizdoom"),
            "iwad": {
                "name": "freedoom2.wad",
                "sha256": sha256(Path(vizdoom.__file__).parent / "freedoom2.wad"),
            },
            "engine_resources": {
                "name": "vizdoom.pk3",
                "sha256": sha256(Path(vizdoom.__file__).parent / "vizdoom.pk3"),
            },
        },
        "assets": {name: sha256(HERE / name) for name in assets},
    }
    (HERE / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")


if __name__ == "__main__":
    main()
