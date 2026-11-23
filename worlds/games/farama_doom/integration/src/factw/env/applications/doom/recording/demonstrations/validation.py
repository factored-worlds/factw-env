"""Closed manifest and reference checks before payload access."""

import hashlib
import json
import math
import re
from dataclasses import asdict

from .types import StreamCapabilities

SCHEMA = "doom.granted-demonstration/1"
STREAMS = {
    "player_rgb": ("rgb", "rgb_uint8_hwc"),
    "language_observations": ("text", "utf_8"),
}
BUTTONS = frozenset(
    {
        "MOVE_FORWARD",
        "MOVE_BACKWARD",
        "MOVE_LEFT",
        "MOVE_RIGHT",
        "TURN_LEFT",
        "TURN_RIGHT",
        "USE",
    }
)
GAP_REASONS = frozenset({"unavailable_capture", "dropped_capture", "recording_interruption"})


def sha256(payload):
    return hashlib.sha256(payload).hexdigest()


def fields(value, expected, label):
    if not isinstance(value, dict) or set(value) != set(expected.split()):
        raise ValueError(f"Invalid {label} fields")


def nonempty(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be nonempty text")


def relative_time(value):
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        raise ValueError("Relative transport time must be finite and nonnegative")
    return float(value)


def integer(value, label):
    if type(value) is not int or value < 0:
        raise ValueError(f"{label} must be a nonnegative integer")


def identifier(value):
    if not isinstance(value, str) or re.fullmatch(r"[a-z][a-z0-9_]*", value) is None:
        raise ValueError("Authored identifiers must use snake_case")


def digest(value):
    if not isinstance(value, str) or re.fullmatch(r"[a-f0-9]{64}", value) is None:
        raise ValueError("Invalid SHA256 digest")


def button_command(buttons):
    if not isinstance(buttons, dict) or not set(buttons) <= BUTTONS:
        raise ValueError("Unsupported pilot button command")
    if any(type(value) is not int or value not in (0, 1) for value in buttons.values()):
        raise ValueError("Button values must be binary integers")
    return dict(buttons)


def decode_json(payload):
    def unique_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate JSON field")
            result[key] = value
        return result

    def invalid_constant(value):
        raise ValueError(f"Nonfinite JSON constant is unsupported: {value}")

    return json.loads(payload, object_pairs_hook=unique_pairs, parse_constant=invalid_constant)


def detached(value):
    return decode_json(json.dumps(value, allow_nan=False).encode("utf-8"))


def validate_manifest(manifest, capabilities, consumer):
    fields(
        manifest,
        "schema source_id source_assistance consumers time_basis streams commands existing_facts",
        "manifest",
    )
    if manifest["schema"] != SCHEMA:
        raise ValueError("Unsupported demonstration schema")
    nonempty(manifest["source_id"], "Source identity")
    if manifest["source_assistance"] not in {"reference_assisted", "unassisted", "authored"}:
        raise ValueError("Unknown source assistance")
    consumers = manifest["consumers"]
    if not isinstance(consumers, list) or not consumers or len(set(consumers)) != len(consumers):
        raise ValueError("Invalid consumer grants")
    for item in consumers:
        identifier(item)
    if consumer not in consumers:
        raise ValueError("Consumer is not granted this demonstration")
    if manifest["time_basis"] != {"kind": "relative_time", "unit": "transport_seconds"}:
        raise ValueError("Unsupported time basis")
    streams = manifest["streams"]
    if not isinstance(streams, list) or not streams:
        raise ValueError("A demonstration requires observation streams")
    stream_ids, payload_paths, references = set(), set(), set()
    for stream in streams:
        fields(stream, "id modality encoding source_id samples gaps", "stream")
        stream_id = stream["id"]
        if stream_id not in STREAMS or stream_id in stream_ids:
            raise ValueError("Unsupported or duplicate observation stream")
        stream_ids.add(stream_id)
        if (stream["modality"], stream["encoding"]) != STREAMS[stream_id]:
            raise ValueError("Unsupported stream encoding")
        if stream["source_id"] != manifest["source_id"]:
            raise ValueError("Stream source differs from declared source")
        supported = capabilities.rgb if stream_id == "player_rgb" else capabilities.text
        if supported is not True:
            raise ValueError("Consumer lacks the declared stream capability")
        samples, gaps = stream["samples"], stream["gaps"]
        if not isinstance(samples, list) or not isinstance(gaps, list) or not (samples or gaps):
            raise ValueError("A stream must retain samples or gaps")
        events, sample_positions = [], {}
        for sample in samples:
            fields(
                sample, "id ordinal relative_time payload_sha256 path shape provenance", "sample"
            )
            nonempty(sample["id"], "Sample identity")
            if sample["id"] in sample_positions:
                raise ValueError("Duplicate sample identity")
            integer(sample["ordinal"], "Sample ordinal")
            if sample["relative_time"] is not None or stream_id != "language_observations":
                relative_time(sample["relative_time"])
            digest(sample["payload_sha256"])
            path = sample["path"]
            suffix = "rgb" if stream_id == "player_rgb" else "txt"
            if (
                not isinstance(path, str)
                or re.fullmatch(rf"assets/[0-9]{{8}}\.{suffix}", path) is None
            ):
                raise ValueError("Asset path is outside the bundle allowlist")
            if path in payload_paths:
                raise ValueError("Duplicate payload path")
            payload_paths.add(path)
            shape = sample["shape"]
            if stream_id == "player_rgb":
                if (
                    not isinstance(shape, list)
                    or len(shape) != 3
                    or shape[2] != 3
                    or any(type(n) is not int or n < 1 for n in shape)
                ):
                    raise ValueError("RGB payload requires an HxWx3 shape")
                if sample["provenance"] != "player_observation":
                    raise ValueError("RGB provenance must be player_observation")
            elif shape is not None or sample["provenance"] not in {
                "player_observation",
                "authored_demonstration",
            }:
                raise ValueError("Invalid text observation provenance")
            sample_positions[sample["id"]] = sample["ordinal"]
            references.add((stream_id, sample["id"]))
            events.append((sample["ordinal"], sample["relative_time"]))
        capture_ids = set(sample_positions)
        for gap in gaps:
            fields(gap, "ordinal relative_time after_sample before_sample reason capture_id", "gap")
            integer(gap["ordinal"], "Gap ordinal")
            if gap["relative_time"] is not None or stream_id != "language_observations":
                relative_time(gap["relative_time"])
            if gap["reason"] not in GAP_REASONS:
                raise ValueError("Unsupported coverage gap reason")
            if gap["capture_id"] is not None:
                nonempty(gap["capture_id"], "Missing capture identity")
                if gap["capture_id"] in capture_ids:
                    raise ValueError("Duplicate available or missing capture identity")
                capture_ids.add(gap["capture_id"])
            for name, before in (("after_sample", True), ("before_sample", False)):
                ref = gap[name]
                if ref is not None and (
                    ref not in sample_positions
                    or (sample_positions[ref] < gap["ordinal"]) != before
                ):
                    raise ValueError("Gap sample reference is missing or out of order")
            events.append((gap["ordinal"], gap["relative_time"]))
        events.sort()
        if [event[0] for event in events] != list(range(len(events))):
            raise ValueError("Every capture ordinal must be present as a sample or gap")
        known_times = [timestamp for _, timestamp in events if timestamp is not None]
        if any(right < left for left, right in zip(known_times, known_times[1:], strict=False)):
            raise ValueError("Transport time must be monotonic within each stream")
        if [sample["ordinal"] for sample in samples] != sorted(sample_positions.values()):
            raise ValueError("Sample ordering is inconsistent")
    if not any(stream["samples"] for stream in streams):
        raise ValueError("A demonstration needs at least one available observation")
    commands = manifest["commands"]
    if commands is not None:
        if not isinstance(commands, list):
            raise ValueError("Invalid command trace")
        previous_time = 0
        command_ids = set()
        for ordinal, command in enumerate(commands):
            fields(command, "id ordinal relative_time command aligned_observations", "command")
            nonempty(command["id"], "Command identity")
            integer(command["ordinal"], "Command ordinal")
            if command["id"] in command_ids or command["ordinal"] != ordinal:
                raise ValueError("Invalid command identity or order")
            command_ids.add(command["id"])
            timestamp = relative_time(command["relative_time"])
            if timestamp < previous_time:
                raise ValueError("Command transport time is not monotonic")
            previous_time = timestamp
            fields(command["command"], "buttons", "button command")
            button_command(command["command"]["buttons"])
            if not isinstance(command["aligned_observations"], list):
                raise ValueError("Invalid explicit observation alignment")
            for ref in command["aligned_observations"]:
                fields(ref, "stream_id sample_id", "command alignment")
                if (ref["stream_id"], ref["sample_id"]) not in references:
                    raise ValueError("Command alignment refers to an unavailable observation")
    facts = manifest["existing_facts"]
    if facts is not None:
        if not isinstance(facts, list):
            raise ValueError("Invalid fact guidance")
        for fact in facts:
            fields(fact, "reference meaning value source_id", "fact guidance")
            for name in ("reference", "meaning", "source_id"):
                nonempty(fact[name], name)


def validate_payload(payload, shape, expected_hash):
    if not isinstance(payload, bytes) or sha256(payload) != expected_hash:
        raise ValueError("Demonstration payload hash mismatch")
    if shape is None:
        payload.decode("utf-8")
    elif len(payload) != shape[0] * shape[1] * shape[2]:
        raise ValueError("RGB payload length does not match its shape")


def validate_demonstration(demonstration):
    if (
        not isinstance(demonstration.manifest_payload, bytes)
        or sha256(demonstration.manifest_payload) != demonstration.manifest_sha256
    ):
        raise ValueError("Detached demonstration requires its exact granted manifest")
    manifest = decode_json(demonstration.manifest_payload)
    validate_manifest(manifest, StreamCapabilities(text=True, rgb=True), "discovery")
    if len(demonstration.streams) != len(manifest["streams"]):
        raise ValueError("Detached demonstration changed after manifest verification")
    projected = detached(manifest)
    projected.update(
        {
            "source_id": demonstration.source_id,
            "source_assistance": demonstration.source_assistance,
            "consumers": list(demonstration.consumers),
            "commands": detached(demonstration.commands),
            "existing_facts": detached(demonstration.existing_facts),
        }
    )
    for stream, declared in zip(demonstration.streams, projected["streams"], strict=False):
        if len(stream.samples) != len(declared["samples"]):
            raise ValueError("Detached stream changed after manifest verification")
        declared.update(
            {
                "id": stream.id,
                "modality": stream.modality,
                "encoding": stream.encoding,
                "source_id": stream.source_id,
                "gaps": [asdict(gap) for gap in stream.gaps],
            }
        )
        for sample, record in zip(stream.samples, declared["samples"], strict=False):
            record.update(
                {
                    "id": sample.id,
                    "ordinal": sample.ordinal,
                    "relative_time": sample.relative_time,
                    "payload_sha256": sample.payload_sha256,
                    "shape": list(sample.shape) if sample.shape is not None else None,
                    "provenance": sample.provenance,
                }
            )
            validate_payload(sample.payload, sample.shape, sample.payload_sha256)
    validate_manifest(projected, StreamCapabilities(text=True, rgb=True), "discovery")
    expected = detached(manifest)
    for stream in expected["streams"]:
        for sample in stream["samples"]:
            if sample["relative_time"] is not None:
                sample["relative_time"] = float(sample["relative_time"])
    if json.dumps(projected, sort_keys=True, allow_nan=False) != json.dumps(
        expected, sort_keys=True, allow_nan=False
    ):
        raise ValueError("Detached demonstration changed after manifest verification")
