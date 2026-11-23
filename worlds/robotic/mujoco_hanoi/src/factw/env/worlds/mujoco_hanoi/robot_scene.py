"""A tabletop task around the pinned MuJoCo Menagerie Franka Panda."""

from math import cos, pi, sin
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile

import mujoco

_ASSETS = Path(__file__).with_name("robot_assets")
_BOARD_X = 0.51
PEG_Y = (-0.145, 0.0, 0.145)
DISK_RADII = (0.018, 0.0245, 0.032)
DISK_THICKNESS = 0.012
PEG_RADIUS = 0.0035
PEG_HEIGHT = 0.050
INNER_RADIUS = 0.007
TRANSIT_Z = 0.15
PARK = (0.34, 0.0, 0.19)
TIP_SITE = "hanoi_grasp"
FINGERS = ("left_finger", "right_finger")

_ASSET_XML = """
<assets>
  <texture type="skybox" builtin="gradient" width="64" height="384"
           rgb1=".16 .21 .22" rgb2=".07 .10 .12"/>
  <texture name="walnut" type="2d" file="walnut.png"/>
  <material name="walnut" texture="walnut" texrepeat="1 1"
            specular=".22" shininess=".25" reflectance=".03"/>
  <material name="bench" rgba=".077 .101 .110 1" specular=".15"/>
  <material name="trim" rgba=".093 .051 .028 1" specular=".27" shininess=".22"/>
  <material name="pin" rgba=".56 .60 .63 1" specular=".78" shininess=".72"/>
  <material name="bronze" rgba=".44 .31 .14 1" specular=".63" shininess=".56"/>
  <material name="disk_0" rgba=".12 .49 .46 1" specular=".38" shininess=".32"/>
  <material name="disk_1" rgba=".84 .57 .23 1" specular=".40" shininess=".30"/>
  <material name="disk_2" rgba=".67 .22 .17 1" specular=".36" shininess=".32"/>
</assets>
"""

_WORKCELL_XML = """
<cell>
  <light name="key" pos=".08 -.39 1.42" dir=".1 .2 -1"
         diffuse=".66 .61 .54" specular=".45 .41 .34" castshadow="true"/>
  <light name="rim" pos=".54 .57 .93" dir="-.2 -.4 -1"
         diffuse=".62 .68 .74" specular=".38 .43 .46" castshadow="false"/>
  <camera name="overview" pos="1.20 -.75 .79"
          xyaxes=".666016 .745938 0 -.312721 .279215 .907879" fovy="46"/>
  <camera name="overhead" pos=".51 0 .62" xyaxes="0 1 0 -1 0 0" fovy="37"/>
  <geom name="bench" type="plane" pos="0 0 -.035" size="1.7 1.2 .1" material="bench"/>
  <geom name="mount" type="cylinder" pos="0 0 -.0175" size=".112 .0175" material="trim"/>
  <geom name="board_core" type="box" pos=".51 0 -.019" size=".092 .216 .011"
        material="trim" contype="0" conaffinity="0"/>
  <geom name="board_top" type="box" pos=".51 0 -.006" size=".088 .212 .006" material="walnut"/>
  <geom name="board_front_inlay" type="box" pos=".599 0 -.014" size=".001 .198 .001"
        material="bronze" contype="0" conaffinity="0"/>
</cell>
"""


def peg_position(peg, z):
    return _BOARD_X, PEG_Y[peg], z


def _numbers(values):
    return " ".join(f"{value:.8g}" for value in values)


def _polar(radius, index, sectors, z):
    angle = 2 * pi * index / sectors
    return radius * cos(angle), radius * sin(angle), z


def _ring_visual(asset, name, radius, sectors=64):
    half = DISK_THICKNESS / 2
    bevel = 0.001
    profile = (
        (INNER_RADIUS, half - bevel),
        (INNER_RADIUS + bevel, half),
        (radius - bevel, half),
        (radius, half - bevel),
        (radius, bevel - half),
        (radius - bevel, -half),
        (INNER_RADIUS + bevel, -half),
        (INNER_RADIUS, bevel - half),
    )
    vertices = [
        coordinate
        for r, z in profile
        for i in range(sectors)
        for coordinate in _polar(r, i, sectors, z)
    ]
    faces = []
    for level in range(len(profile)):
        following = (level + 1) % len(profile)
        for index in range(sectors):
            next_index = (index + 1) % sectors
            a, b = level * sectors + index, level * sectors + next_index
            c, d = following * sectors + index, following * sectors + next_index
            faces.extend((a, d, b, a, c, d))
    ET.SubElement(asset, "mesh", name=name, vertex=_numbers(vertices), face=_numbers(faces))


def _disk(root, asset, disk, radius):
    name = f"hanoi_disk_{disk}"
    peg_z = DISK_THICKNESS * (len(DISK_RADII) - disk - 0.5)
    body = ET.SubElement(root, "body", name=name, pos=_numbers(peg_position(0, peg_z)))
    ET.SubElement(body, "freejoint", name=f"{name}_joint")
    _ring_visual(asset, name, radius)
    ET.SubElement(
        body,
        "geom",
        type="mesh",
        mesh=name,
        material=f"disk_{disk}",
        contype="0",
        conaffinity="0",
        mass="0",
    )
    sectors = 16
    for sector in range(sectors):
        points = [
            coordinate
            for z in (-DISK_THICKNESS / 2, DISK_THICKNESS / 2)
            for r, index in (
                (INNER_RADIUS, sector),
                (radius, sector),
                (radius, sector + 1),
                (INNER_RADIUS, sector + 1),
            )
            for coordinate in _polar(r, index, sectors, z)
        ]
        collider = f"{name}_sector_{sector}"
        ET.SubElement(asset, "mesh", name=collider, vertex=_numbers(points))
        ET.SubElement(
            body,
            "geom",
            type="mesh",
            mesh=collider,
            group="3",
            mass=f"{(0.014 + 0.007 * disk) / sectors:.8g}",
            friction="1.7 .006 .001",
            condim="4",
            solref=".008 1",
            solimp=".95 .99 .001",
        )


def _gripper(model):
    hand = model.find(".//body[@name='hand']")
    ET.SubElement(hand, "site", name=TIP_SITE, pos="0 0 .1234", size=".001", rgba="0 0 0 0")
    for finger_name in FINGERS:
        finger = hand.find(f"body[@name='{finger_name}']")
        ET.SubElement(
            finger,
            "geom",
            name=f"{finger_name}_insert",
            type="box",
            pos="0 .0058 .056",
            size=".0075 .0035 .013",
            mass=".003",
            rgba=".12 .14 .16 1",
            contype="0",
            conaffinity="0",
        )
        ET.SubElement(
            finger,
            "geom",
            name=f"{finger_name}_pad",
            type="box",
            pos="0 .00475 .065",
            size=".009 .0038 .004",
            mass=".004",
            rgba=".09 .11 .12 1",
            friction="2.6 .012 .002",
            condim="4",
            solref=".007 1",
            solimp=".95 .99 .001",
        )
    gripper_actuator = model.find("actuator/general[@name='actuator8']")
    gripper_actuator.set("gainprm", ".068 0 0")
    gripper_actuator.set("biasprm", "0 -433.5 -10")
    gripper_actuator.set("forcerange", "-16 16")


def build_model():
    model = ET.parse(_ASSETS / "panda.xml").getroot()
    model.set("model", "franka_panda_hanoi")
    model.find("option").set("timestep", f"{1 / 600:.16g}")
    model.find("option").set("cone", "elliptic")
    model.find("option").set("iterations", "70")
    asset, world = model.find("asset"), model.find("worldbody")
    visual = ET.SubElement(model, "visual")
    ET.SubElement(visual, "headlight", active="1", ambient=".31 .33 .36", diffuse=".27 .27 .27")
    ET.SubElement(visual, "global", offwidth="1920", offheight="1080")
    ET.SubElement(visual, "quality", shadowsize="2048", offsamples="4")
    asset.extend(ET.fromstring(_ASSET_XML))
    world.extend(ET.fromstring(_WORKCELL_XML))
    for body in world.find("body").iter("body"):
        body.set("gravcomp", "1")
    _gripper(model)
    for peg, position in enumerate(PEG_Y):
        ET.SubElement(
            world,
            "geom",
            name=f"hanoi_peg_{peg}",
            type="cylinder",
            pos=_numbers((_BOARD_X, position, PEG_HEIGHT / 2)),
            size=_numbers((PEG_RADIUS, PEG_HEIGHT / 2)),
            material="pin",
        )
        ET.SubElement(
            world,
            "geom",
            name=f"peg_bearing_{peg}",
            type="cylinder",
            pos=_numbers((_BOARD_X, position, 0.0005)),
            size=".0064 .001",
            material="bronze",
            contype="0",
            conaffinity="0",
        )
    for disk, radius in enumerate(DISK_RADII):
        _disk(world, asset, disk, radius)
    with ZipFile(_ASSETS / "franka_meshes.zip") as mesh_archive:
        assets = {name: mesh_archive.read(name) for name in mesh_archive.namelist()}
    assets["walnut.png"] = (_ASSETS / "walnut.png").read_bytes()
    return mujoco.MjModel.from_xml_string(ET.tostring(model, encoding="unicode"), assets)
