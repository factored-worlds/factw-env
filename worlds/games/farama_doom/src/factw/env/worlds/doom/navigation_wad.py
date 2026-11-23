"""Encode a sampled navigation layout as one ZDoom UDMF map."""

from .scenarios.retrieve_key_and_escape.assets.build import block, wad


def _edges(points):
    return zip(points, points[1:] + points[:1], strict=True)


def _thing(position, kind, angle=0, tid=0):
    return {
        "x": float(position[0]),
        "y": float(position[1]),
        "angle": angle,
        "type": kind,
        "id": tid,
        "skill1": True,
        "skill2": True,
        "skill3": True,
        "skill4": True,
        "skill5": True,
        "single": True,
    }


def navigation_wad(layout, behavior):
    sectors = layout["sectors"]
    vertices = dict.fromkeys(
        tuple(point) for sector in sectors for point in sector["polygon"]
    )
    vertex_id = {point: i for i, point in enumerate(vertices)}
    panel = frozenset(map(tuple, layout["exit_panel"]))
    sides, lines, edges = [], [], {}
    for index, sector in enumerate(sectors):
        for start, end in _edges(list(map(tuple, sector["polygon"]))):
            side = {
                "sector": index,
                "texturetop": "STARTAN3",
                "texturebottom": "STARTAN3",
                "texturemiddle": "EXITDOOR"
                if frozenset((start, end)) == panel
                else "STARTAN3",
            }
            other = edges.get((end, start))
            if other is None:
                edges[start, end] = len(lines)
                lines.append(
                    {
                        "v1": vertex_id[start],
                        "v2": vertex_id[end],
                        "sidefront": len(sides),
                        "blocking": True,
                    }
                )
            else:
                line = lines[other]
                front = sides[line["sidefront"]]
                window = sector["name"] == "monster_bay"
                line.update(sideback=len(sides), twosided=True, blocking=window)
                front["texturemiddle"] = side["texturemiddle"] = "-"
                if not window:
                    front["texturetop"] = side["texturetop"] = "DOORBLU"
                    line.update(special=80, arg0=2, playeruse=True, repeatspecial=True)
            sides.append(side)
    text = ['namespace = "ZDoom";\n\n']
    text.extend(block("vertex", {"x": float(x), "y": float(y)}) for x, y in vertices)
    for sector in sectors:
        text.append(
            block(
                "sector",
                {
                    "heightfloor": sector["floor"],
                    "heightceiling": sector["ceiling"],
                    "texturefloor": "FLOOR0_1",
                    "textureceiling": "CEIL1_1",
                    "lightlevel": 224,
                    "id": sector["tag"],
                },
            )
        )
    for kind, rows in (("sidedef", sides), ("linedef", lines)):
        text.extend(block(kind, row) for row in rows)
    spawn = layout["spawn"]
    things = [
        _thing(spawn["position"], 1, spawn["angle"]),
        _thing(layout["key_position"], 5),
    ]
    # MapSpot TIDs match the constants in seeded_task.acs; they have no physical body.
    for tid, point in enumerate(
        (
            layout["door_center"],
            layout["scene_spec"]["door_approach"],
            layout["door_far_threshold"],
            layout["exit_position"],
        ),
        start=900,
    ):
        things.append(_thing(point, 9001, tid=tid))
    for enemy in layout["enemies"]:
        things.append(_thing(enemy["position"], enemy["type"], enemy["angle"]))
    text.extend(block("thing", thing) for thing in things)
    return wad(
        [
            ("MAP01", b""),
            ("TEXTMAP", "".join(text).encode()),
            ("BEHAVIOR", behavior),
            ("ENDMAP", b""),
        ]
    )
