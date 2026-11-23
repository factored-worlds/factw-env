"""Read one explicit demonstration export without following outside paths."""

from hashlib import sha256
from pathlib import Path, PurePosixPath

from .inputs import GrantedRequest, decode_json_bytes


def read_granted_request(directory, original_goal):
    root = Path(directory).resolve(strict=True)

    def read_path(name):
        path = PurePosixPath(name)
        if path.is_absolute() or ".." in path.parts or not path.parts:
            raise ValueError("Export resources must be relative paths inside the export")
        source = (root / path).resolve(strict=True)
        if not source.is_relative_to(root):
            raise ValueError("Export resources must remain inside the export")
        return source.read_bytes()

    def read(record, expected_hash):
        payload = read_path(record["path"])
        if sha256(payload).hexdigest() != expected_hash:
            raise ValueError("Export resource hash mismatch")
        return payload

    manifest = decode_json_bytes(read_path("manifest.json"))
    if manifest.get("schema") != "doom.demonstration-request-export/1":
        raise ValueError("Expected a demonstration request export")
    request = read(manifest["request"], manifest["request"]["sha256"])
    coverage = read(manifest["coverage"], manifest["coverage"]["sha256"])
    assets = {
        name: read(record, record["payload_sha256"]) for name, record in manifest["assets"].items()
    }
    return GrantedRequest(request, coverage, assets, Path(original_goal).read_bytes())
