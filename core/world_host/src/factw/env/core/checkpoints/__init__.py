"""Versioned engine checkpoints with an explicitly selected world codec."""

import json
from collections.abc import Callable
from dataclasses import dataclass

from factw.env.core.checkpoints._fields import members
from factw.env.core.recording.jsonio import json_object

__all__ = ["SnapshotCodec", "dumps_snapshot", "loads_snapshot"]


@dataclass(frozen=True, slots=True)
class SnapshotCodec[T]:
    engine: str
    snapshot_type: type[T]
    encode: Callable[[T], dict]
    decode: Callable[[object], T]


def dumps_snapshot[T](snapshot: T, *, codec: SnapshotCodec[T]) -> str:
    if not isinstance(snapshot, codec.snapshot_type):
        raise TypeError(f"Expected {codec.snapshot_type.__name__}")
    document = {
        "format": "factored-worlds-engine",
        "version": "1",
        "engine": codec.engine,
        "snapshot": codec.encode(snapshot),
    }
    source = json.dumps(document, indent=2, allow_nan=False) + "\n"
    if loads_snapshot(source, codec=codec) != snapshot:
        raise ValueError("Snapshot fields do not match the engine checkpoint schema")
    return source


def loads_snapshot[T](source: str, *, codec: SnapshotCodec[T]) -> T:
    document = members(json_object(source), {"format", "version", "engine", "snapshot"})
    if document["format"] != "factored-worlds-engine" or document["version"] != "1":
        raise ValueError("Unsupported engine checkpoint format or version")
    if document["engine"] != codec.engine:
        raise ValueError(f"Expected {codec.engine!r} checkpoint engine")
    return codec.decode(document["snapshot"])
