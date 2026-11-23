"""Write only explicitly supplied player observations and guidance."""

import json
from pathlib import Path

import numpy as np

from ...information.player_observation import PlayerObservation
from .types import StreamCapabilities
from .validation import (
    GAP_REASONS,
    SCHEMA,
    STREAMS,
    button_command,
    detached,
    identifier,
    nonempty,
    sha256,
    validate_manifest,
)
from .validation import (
    relative_time as validate_relative_time,
)


class DemonstrationWriter:
    def __init__(
        self, path, *, source_id, consumers=("discovery",), assistance="reference_assisted"
    ):
        nonempty(source_id, "Source identity")
        if assistance not in {"reference_assisted", "unassisted", "authored"}:
            raise ValueError("Unknown source assistance")
        if not consumers or len(set(consumers)) != len(consumers):
            raise ValueError("Consumer grants must be nonempty and unique")
        for consumer in consumers:
            identifier(consumer)
        self.path = Path(path)
        self.path.mkdir(parents=True, exist_ok=False)
        (self.path / "assets").mkdir()
        self._closed = False
        self._asset_count = 0
        self._manifest = {
            "schema": SCHEMA,
            "source_id": source_id,
            "source_assistance": assistance,
            "consumers": list(consumers),
            "time_basis": {"kind": "relative_time", "unit": "transport_seconds"},
            "streams": [],
            "commands": None,
            "existing_facts": None,
        }

    def __enter__(self):
        self._open()
        return self

    def __exit__(self, exception_type, exception, traceback):
        if exception_type is None:
            self.close()
        else:
            self._closed = True

    def _open(self):
        if self._closed:
            raise ValueError("Demonstration writer is closed")

    def _stream(self, stream_id):
        self._open()
        if stream_id not in STREAMS:
            raise ValueError("Unsupported observation stream")
        for stream in self._manifest["streams"]:
            if stream["id"] == stream_id:
                return stream
        modality, encoding = STREAMS[stream_id]
        stream = {
            "id": stream_id,
            "modality": modality,
            "encoding": encoding,
            "source_id": self._manifest["source_id"],
            "samples": [],
            "gaps": [],
        }
        self._manifest["streams"].append(stream)
        return stream

    def _sample(self, stream_id, sample_id, timestamp, payload, shape, provenance):
        stream = self._stream(stream_id)
        nonempty(sample_id, "Sample identity")
        timestamp = (
            None
            if timestamp is None and stream_id == "language_observations"
            else validate_relative_time(timestamp)
        )
        self._check_time(stream, timestamp)
        if any(sample["id"] == sample_id for sample in stream["samples"]):
            raise ValueError("Duplicate sample identity")
        suffix = "rgb" if shape is not None else "txt"
        path = f"assets/{self._asset_count:08d}.{suffix}"
        with (self.path / path).open("xb") as handle:
            handle.write(payload)
        self._asset_count += 1
        stream["samples"].append(
            {
                "id": sample_id,
                "ordinal": len(stream["samples"]) + len(stream["gaps"]),
                "relative_time": timestamp,
                "payload_sha256": sha256(payload),
                "path": path,
                "shape": shape,
                "provenance": provenance,
            }
        )
        return {"stream_id": stream_id, "sample_id": sample_id}

    @staticmethod
    def _check_time(stream, timestamp):
        if timestamp is None:
            return
        events = [
            item for item in stream["samples"] + stream["gaps"] if item["relative_time"] is not None
        ]
        if events and timestamp < max(item["relative_time"] for item in events):
            raise ValueError("Transport time must be monotonic within each stream")

    def add_rgb(self, observation, *, relative_time):
        if not isinstance(observation, PlayerObservation):
            raise ValueError("RGB recording requires a detached PlayerObservation")
        rgb = observation.rgb
        if (
            not isinstance(rgb, np.ndarray)
            or rgb.dtype != np.uint8
            or rgb.ndim != 3
            or rgb.shape[2] != 3
            or min(rgb.shape[:2]) < 1
        ):
            raise ValueError("RGB payload must be HxWx3 uint8")
        return self._sample(
            "player_rgb",
            observation.capture_id,
            relative_time,
            rgb.tobytes(order="C"),
            list(rgb.shape),
            "player_observation",
        )

    def add_text(self, text, *, sample_id, relative_time=None, provenance="authored_demonstration"):
        if not isinstance(text, str) or not text.strip():
            raise ValueError("Demonstration text must be nonempty")
        if provenance not in {"authored_demonstration", "player_observation"}:
            raise ValueError("Unsupported text provenance")
        return self._sample(
            "language_observations",
            sample_id,
            relative_time,
            text.encode("utf-8"),
            None,
            provenance,
        )

    def add_gap(
        self,
        *,
        relative_time=None,
        stream_id="player_rgb",
        after_sample,
        before_sample=None,
        reason="unavailable_capture",
        capture_id=None,
    ):
        stream = self._stream(stream_id)
        timestamp = (
            None
            if relative_time is None and stream_id == "language_observations"
            else validate_relative_time(relative_time)
        )
        self._check_time(stream, timestamp)
        if reason not in GAP_REASONS:
            raise ValueError("Unsupported coverage gap reason")
        if capture_id is not None:
            nonempty(capture_id, "Missing capture identity")
        stream["gaps"].append(
            {
                "ordinal": len(stream["samples"]) + len(stream["gaps"]),
                "relative_time": timestamp,
                "after_sample": after_sample,
                "before_sample": before_sample,
                "reason": reason,
                "capture_id": capture_id,
            }
        )

    def add_command(self, buttons, *, relative_time, aligned_observations=()):
        self._open()
        command = button_command(buttons)
        timestamp = validate_relative_time(relative_time)
        if self._manifest["commands"] is None:
            self._manifest["commands"] = []
        commands = self._manifest["commands"]
        if commands and timestamp < commands[-1]["relative_time"]:
            raise ValueError("Command transport time must be monotonic")
        commands.append(
            {
                "id": f"command_{len(commands):06d}",
                "ordinal": len(commands),
                "relative_time": timestamp,
                "command": {"buttons": command},
                "aligned_observations": detached(list(aligned_observations)),
            }
        )

    def add_fact(self, *, reference, meaning, value, source_id):
        self._open()
        for item in (reference, meaning, source_id):
            nonempty(item, "Fact guidance")
        if self._manifest["existing_facts"] is None:
            self._manifest["existing_facts"] = []
        self._manifest["existing_facts"].append(
            detached(
                {
                    "reference": reference,
                    "meaning": meaning,
                    "value": value,
                    "source_id": source_id,
                }
            )
        )

    def close(self):
        if self._closed:
            return self.path
        validate_manifest(
            self._manifest, StreamCapabilities(text=True, rgb=True), self._manifest["consumers"][0]
        )
        payload = (
            json.dumps(self._manifest, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
        ).encode("utf-8")
        with (self.path / "manifest.json").open("xb") as handle:
            handle.write(payload)
        self._closed = True
        return self.path
