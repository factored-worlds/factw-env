import json
from pathlib import Path

RESERVED = {"annotations", "privileged"}


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON object key {key!r}")
        result[key] = value
    return result


def _constant(value):
    raise ValueError(f"Nonfinite JSON number {value}")


def json_value(source: str):
    value = json.loads(source, object_pairs_hook=_object, parse_constant=_constant)
    json.dumps(value, allow_nan=False, ensure_ascii=False).encode("utf-8")
    return value


def json_object(source: str) -> dict:
    value = json_value(source)
    if type(value) is not dict:
        raise ValueError("Expected a JSON object")
    return value


def read_json(path: Path) -> dict:
    return json_object(path.read_text(encoding="utf-8"))


def asset_path(root: Path, value: str) -> Path:
    if (
        type(value) is not str
        or "\\" in value
        or "\0" in value
        or any(part in {"", ".", ".."} | RESERVED for part in value.split("/"))
    ):
        raise ValueError("Assets require normalized relative public POSIX paths")
    path = root / value
    resolved_root, resolved = root.resolve(), path.resolve()
    if not resolved.is_relative_to(resolved_root):
        raise ValueError("An asset path escapes its episode")
    if RESERVED.intersection(resolved.relative_to(resolved_root).parts):
        raise ValueError("An asset path references privileged annotations")
    return path
