"""Detached, explicitly granted demonstration data."""

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class StreamCapabilities:
    text: bool = False
    rgb: bool = False


@dataclass(frozen=True)
class Sample:
    id: str
    ordinal: int
    relative_time: float | None
    payload_sha256: str
    payload: bytes
    shape: tuple[int, int, int] | None
    provenance: str

    @property
    def text(self):
        if self.shape is not None:
            raise ValueError("RGB samples are not text")
        return self.payload.decode("utf-8")

    @property
    def rgb(self):
        if self.shape is None:
            raise ValueError("Text samples are not RGB")
        return np.frombuffer(self.payload, dtype=np.uint8).reshape(self.shape)


@dataclass(frozen=True)
class Gap:
    ordinal: int
    relative_time: float | None
    after_sample: str | None
    before_sample: str | None
    reason: str
    capture_id: str | None


@dataclass(frozen=True)
class ObservationStream:
    id: str
    modality: str
    encoding: str
    source_id: str
    samples: tuple[Sample, ...]
    gaps: tuple[Gap, ...]


@dataclass(frozen=True)
class Demonstration:
    source_id: str
    source_assistance: str
    consumers: tuple[str, ...]
    streams: tuple[ObservationStream, ...]
    commands: tuple[dict, ...] | None
    existing_facts: tuple[dict, ...] | None
    manifest_sha256: str
    manifest_payload: bytes = b""


@dataclass(frozen=True)
class RequestExport:
    request: dict
    assets: dict[str, bytes]
    coverage: dict
