"""Procedural Hanoi rings and a Cartesian parallel-jaw gripper."""

from math import cos, pi, sin
from pathlib import Path

_TEMPLATE = Path(__file__).with_name("hanoi.xml").read_text()

PEG_X = (-0.28, 0.0, 0.28)
THICKNESS = 0.022
SAFE_Z = 0.32
HOME = (-0.28, -0.20, SAFE_Z, 0.15)
COLORS = tuple(
    tuple(c / 255 for c in rgb)
    for rgb in ((145, 150, 160), (230, 185, 40), (65, 155, 95), (90, 180, 190), (170, 110, 210))
)
PEG_COLORS = ((0.49, 0.33, 0.22), (0.20, 0.39, 0.71), (0.71, 0.25, 0.22))


def radius(disk: int) -> float:
    return 0.045 + 0.018 * disk


def model_xml(pegs: tuple[int, ...]) -> str:
    meshes, bodies = [], []
    for disk, peg in enumerate(pegs):
        geoms = []
        for sector in range(16):
            points = []
            for z in (-THICKNESS / 2, THICKNESS / 2):
                for r, a in (
                    (0.014, sector),
                    (radius(disk), sector),
                    (radius(disk), sector + 1),
                    (0.014, sector + 1),
                ):
                    points.extend((r * cos(a * pi / 8), r * sin(a * pi / 8), z))
            name = f"ring_{disk}_{sector}"
            meshes.append(f'<mesh name="{name}" vertex="{" ".join(map(str, points))}"/>')
            color = " ".join(map(str, (*COLORS[disk], 1)))
            geoms.append(
                f'<geom type="mesh" mesh="{name}" '
                f'mass="{(0.06 + 0.02 * disk) / 16}" rgba="{color}"/>'
            )
        below = sum(p == peg for p in pegs[disk + 1 :])
        z = THICKNESS * (below + 0.5)
        bodies.append(
            f'<body name="disk_{disk}" pos="{PEG_X[peg]} 0 {z}">'
            f'<freejoint name="disk_joint_{disk}"/>{"".join(geoms)}</body>'
        )
    peg_height = THICKNESS * len(pegs) + 0.055
    poles = "".join(
        f'<geom name="peg_{i}" type="cylinder" pos="{x} 0 {peg_height / 2}" '
        f'size="0.008 {peg_height / 2}" rgba="{" ".join(map(str, (*PEG_COLORS[i], 1)))}"/>'
        for i, x in enumerate(PEG_X)
    )
    return _TEMPLATE.format(meshes="".join(meshes), bodies="".join(bodies), poles=poles)
