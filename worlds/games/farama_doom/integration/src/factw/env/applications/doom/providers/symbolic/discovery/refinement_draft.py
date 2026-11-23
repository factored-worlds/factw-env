"""Materialize transport hashes without rewriting proposed source or semantics."""

import hashlib
import json
from importlib.resources import files

from jsonschema import Draft202012Validator

from ....refinement.inputs import GrantedRequest, decode_json_bytes


def encoded(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2).encode("utf-8")


def digest(payload):
    return hashlib.sha256(payload).hexdigest()


def draft_schema():
    """The candidate contract with only host-computed transport hashes omitted."""
    schema = decode_json_bytes(
        files("factw.env.applications.doom.refinement")
        .joinpath("schemas", "candidate.schema.json")
        .read_bytes()
    )
    for name in ("request_sha256", "original_goal_sha256"):
        del schema["properties"][name]
        schema["required"].remove(name)
    document = schema["$defs"]["document"]
    del document["properties"]["sha256"]
    document["required"].remove("sha256")
    schema["properties"]["origin"] = {"const": "model_proposal"}
    return schema


def materialize_candidate(payload, request):
    """Keep exact model source strings; insert hashes over those UTF-8 bytes."""
    if type(request) is not GrantedRequest:
        raise ValueError("A sealed granted request is required")
    draft = decode_json_bytes(payload)
    errors = sorted(
        Draft202012Validator(draft_schema()).iter_errors(draft),
        key=lambda error: list(map(str, error.path)),
    )
    if errors:
        error = errors[0]
        location = "/".join(map(str, error.absolute_path)) or "root"
        raise ValueError(f"Invalid candidate draft at {location}: {error.message}")
    draft["request_sha256"] = request.sha256
    draft["original_goal_sha256"] = digest(request.original_goal)
    for document in draft["documents"]:
        document["sha256"] = digest(document["source"].encode("utf-8"))
    return encoded(draft)
