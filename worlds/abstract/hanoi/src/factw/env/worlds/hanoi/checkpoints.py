from dataclasses import asdict

from factw.env.core import checkpoints
from factw.env.core.checkpoints import SnapshotCodec
from factw.env.core.checkpoints._fields import array, record
from factw.env.worlds.hanoi import (
    HanoiEnv,
    HanoiSnapshot,
    HanoiState,
    HanoiTask,
    RenderStyle,
)


def snapshot_to_dict(snapshot: HanoiSnapshot) -> dict:
    HanoiEnv(snapshot.task, style=snapshot.style).restore(snapshot)
    return asdict(snapshot)


def snapshot_from_dict(value: object) -> HanoiSnapshot:
    values = record(value, HanoiSnapshot)
    task_values = record(values["task"], HanoiTask)
    task = HanoiTask(
        start=array(task_values["start"]),
        goal=array(task_values["goal"]),
        max_steps=task_values["max_steps"],
    )
    state = HanoiState(array(record(values["state"], HanoiState)["pegs"]))
    style_values = record(values["style"], RenderStyle)
    style = RenderStyle(
        background=array(style_values["background"]),
        disk_colors=tuple(array(color) for color in array(style_values["disk_colors"])),
        peg_colors=tuple(array(color) for color in array(style_values["peg_colors"])),
        offset=array(style_values["offset"]),
    )
    snapshot = HanoiSnapshot(task, state, values["steps"], style)
    HanoiEnv(task, style=style).restore(snapshot)
    return snapshot


CODEC = SnapshotCodec("hanoi", HanoiSnapshot, snapshot_to_dict, snapshot_from_dict)


def dumps_snapshot(snapshot: HanoiSnapshot) -> str:
    return checkpoints.dumps_snapshot(snapshot, codec=CODEC)


def loads_snapshot(source: str) -> HanoiSnapshot:
    return checkpoints.loads_snapshot(source, codec=CODEC)
