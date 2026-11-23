"""Validate detached, explicitly granted bytes without resolving external resources."""

import math
from collections.abc import Mapping
from dataclasses import dataclass
from importlib.resources import files
from types import MappingProxyType

from jsonschema import Draft202012Validator

from ..recording.demonstrations.validation import (
    button_command,
    decode_json,
    detached,
    fields,
    integer,
    nonempty,
    relative_time,
    sha256,
)
from .request_coverage import validate_coverage

MAX_DOCUMENTS = 16
MAX_SOURCE_BYTES = 128 * 1024


def decode_json_bytes(payload):
    """Decode finite UTF-8 JSON while rejecting duplicate fields at every depth."""
    if type(payload) is not bytes:
        raise ValueError("Exact UTF-8 bytes are required")
    value = decode_json(payload.decode("utf-8"))

    def finite(node):
        if isinstance(node, float) and not math.isfinite(node):
            raise ValueError("Nonfinite JSON numbers are unsupported")
        if isinstance(node, dict):
            for item in node.values():
                finite(item)
        elif isinstance(node, list):
            for item in node:
                finite(item)

    finite(value)
    return value


def _schema(value, name):
    schema = decode_json_bytes(
        files(__package__).joinpath("schemas", f"{name}.schema.json").read_bytes()
    )
    errors = sorted(
        Draft202012Validator(schema).iter_errors(value), key=lambda e: list(map(str, e.path))
    )
    if errors:
        error = errors[0]
        location = "/".join(map(str, error.absolute_path)) or "root"
        raise ValueError(f"Invalid {name} envelope at {location}: {error.message}")


def _unique(records, key, label):
    values = [record[key] for record in records]
    if len(values) != len(set(values)):
        raise ValueError(f"Duplicate {label}")


def _documents(documents):
    if len(documents) > MAX_DOCUMENTS:
        raise ValueError("At most 16 documents are permitted")
    _unique(documents, "id", "document identity")
    source_bytes = [document["source"].encode("utf-8") for document in documents]
    if sum(map(len, source_bytes)) > MAX_SOURCE_BYTES:
        raise ValueError("Aggregate SMSL source exceeds 128 KiB UTF-8 bytes")
    for document, payload in zip(documents, source_bytes, strict=True):
        if document["sha256"] != sha256(payload):
            raise ValueError("SMSL source hash mismatch")


def _reference(reference):
    nonempty(reference["stream_id"], "Observation stream identity")
    nonempty(reference["sample_id"], "Observation sample identity")
    return reference["stream_id"], reference["sample_id"]


def _guidance(request, coverage, samples):
    guidance = request.get("guidance", {})
    _documents(guidance.get("prior_smsl_documents", []))
    _unique(guidance.get("primitive_descriptions", []), "id", "primitive description identity")
    commands = guidance.get("recorded_commands", [])
    _unique(commands, "id", "command identity")
    previous_time = 0
    for ordinal, command in enumerate(commands):
        integer(command["ordinal"], "Command ordinal")
        if command["ordinal"] != ordinal:
            raise ValueError("Command ordinals must retain their recorded order")
        if command["relative_time"] is not None:
            timestamp = relative_time(command["relative_time"])
            if timestamp < previous_time:
                raise ValueError("Command transport time must be monotonic")
            previous_time = timestamp
        fields(command["command"], "buttons", "recorded button command")
        button_command(command["command"]["buttons"])
        refs = [_reference(ref) for ref in command["aligned_observations"]]
        if len(refs) != len(set(refs)) or not set(refs) <= samples.keys():
            raise ValueError("Command alignment requires unique granted observations")
    unexported = coverage["unexported_command_alignment"]
    if not isinstance(unexported, list):
        raise ValueError("Invalid unexported command alignment")
    command_ids = {command["id"] for command in commands}
    covered = {
        (record["stream_id"], item["sample_id"])
        for record in coverage["streams"]
        for item in record["sample_provenance"]
    }
    seen = set()
    for item in unexported:
        fields(item, "command_id unexported_observations", "unexported alignment")
        nonempty(item["command_id"], "Command identity")
        if (
            item["command_id"] not in command_ids
            or item["command_id"] in seen
            or not isinstance(item["unexported_observations"], list)
            or not item["unexported_observations"]
        ):
            raise ValueError("Unexported alignment lacks a unique recorded command")
        seen.add(item["command_id"])
        refs = []
        for ref in item["unexported_observations"]:
            fields(ref, "stream_id sample_id", "unexported observation")
            refs.append(_reference(ref))
        if len(refs) != len(set(refs)) or any(ref not in covered or ref in samples for ref in refs):
            raise ValueError("Unexported alignment must refer only to omitted observations")


@dataclass(frozen=True, init=False)
class GrantedRequest:
    """Sealed transport bytes supplied by the host after its information grant.

    Hashes and labels establish transport integrity, not the authenticity of
    authored observations. This boundary never reads paths or executes guidance.
    """

    request_bytes: bytes
    coverage_bytes: bytes
    original_goal: bytes
    assets: Mapping[str, bytes]

    def __init__(self, request_bytes, coverage_bytes, assets, original_goal):
        request, coverage, goal = map(
            decode_json_bytes, (request_bytes, coverage_bytes, original_goal)
        )
        _schema(request, "request")
        if request["original_goal"] != {"sha256": sha256(original_goal), "document": goal}:
            raise ValueError("Request changed the exact original goal")
        if type(goal["scenario_behavior_revision"]) is not int:
            raise ValueError("Scenario behavior revision must be an integer")
        _unique(goal["clauses"], "id", "original-goal clause identity")
        _unique(request["observation_streams"], "id", "observation stream identity")
        for stream in request["observation_streams"]:
            _unique(stream["samples"], "id", "sample identity")
            for sample in stream["samples"]:
                integer(sample["ordinal"], "Sample ordinal")
        if not isinstance(assets, Mapping) or any(
            not isinstance(key, str) or type(value) is not bytes for key, value in assets.items()
        ):
            raise ValueError("Assets must be an explicit mapping of opaque IDs to bytes")
        assets = dict(assets)
        validate_coverage(request, coverage, assets)
        samples = {
            (stream["id"], sample["id"]): sample
            for stream in request["observation_streams"]
            for sample in stream["samples"]
        }
        _guidance(request, coverage, samples)
        for name, value in (
            ("request_bytes", request_bytes),
            ("coverage_bytes", coverage_bytes),
            ("original_goal", original_goal),
            ("assets", MappingProxyType(assets)),
        ):
            object.__setattr__(self, name, value)

    @property
    def sha256(self):
        return sha256(self.request_bytes)

    @property
    def request(self):
        return decode_json_bytes(self.request_bytes)

    @property
    def coverage(self):
        return decode_json_bytes(self.coverage_bytes)

    @property
    def streams(self):
        return {stream["id"]: stream for stream in self.request["observation_streams"]}

    @property
    def samples(self):
        return {
            (stream["id"], sample["id"]): sample
            for stream in self.streams.values()
            for sample in stream["samples"]
        }


def validate_candidate_bytes(payload, request):
    """Validate envelope integrity; supported labels do not grant claim authority."""
    if type(request) is not GrantedRequest:
        raise ValueError("A sealed granted request is required")
    candidate = decode_json_bytes(payload)
    _schema(candidate, "candidate")
    if candidate["request_sha256"] != request.sha256 or candidate["original_goal_sha256"] != sha256(
        request.original_goal
    ):
        raise ValueError("Candidate input hash differs from the granted request or goal")
    _documents(candidate["documents"])
    for name in (
        "state_correspondence",
        "action_refinements",
        "grounding",
        "evidence",
        "unresolved",
    ):
        _unique(candidate[name], "id", f"{name} identity")
    _unique(candidate["world_instances"], "instance_id", "world instance identity")
    _unique(candidate["goal_correspondence"], "goal_clause_id", "goal clause correspondence")
    imports = [
        (item["from_document"], item["import_name"]) for item in candidate["import_bindings"]
    ]
    if len(imports) != len(set(imports)):
        raise ValueError("Duplicate import binding")
    leaves = [
        (item["leaf"]["document_id"], item["leaf"]["address"])
        for item in candidate["primitive_bindings"]
    ]
    if len(leaves) != len(set(leaves)):
        raise ValueError("Duplicate primitive leaf binding")
    samples = request.samples
    for evidence in candidate["evidence"]:
        refs = [_reference(ref) for ref in evidence["observations"]]
        if len(refs) != len(set(refs)) or not set(refs) <= samples.keys():
            raise ValueError("Evidence must refer to unique covered granted observations")
        if evidence["assessment"] == "supported" and not refs:
            raise ValueError("Supported claims require covered granted observations")
    for binding in candidate["primitive_bindings"]:
        button_command(binding["arguments"]["buttons"])
    return detached(candidate)
