"""Read the closed granted bundle without resolving external recordings."""

import os
import stat
from pathlib import Path

from .types import Demonstration, Gap, ObservationStream, Sample, StreamCapabilities
from .validation import decode_json, detached, sha256, validate_manifest, validate_payload


def _read_file(directory, name):
    descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory)
    with os.fdopen(descriptor, "rb") as handle:
        if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
            raise ValueError("Bundle payload must be a regular file")
        return handle.read()


def read_demonstration(path, *, capabilities, consumer="discovery"):
    if not isinstance(capabilities, StreamCapabilities):
        raise ValueError("Explicit stream capabilities are required")
    root = Path(path).absolute()
    if root.resolve() != root:
        raise ValueError("Demonstration bundle paths cannot contain symlinks")
    directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        manifest_payload = _read_file(directory, "manifest.json")
        manifest = decode_json(manifest_payload)
        validate_manifest(manifest, capabilities, consumer)
        asset_directory = os.open(
            "assets", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory
        )
        try:
            for stream in manifest["streams"]:
                for sample in stream["samples"]:
                    info = os.stat(
                        sample["path"].split("/")[1], dir_fd=asset_directory, follow_symlinks=False
                    )
                    if not stat.S_ISREG(info.st_mode):
                        raise ValueError("Bundle assets must be regular files without symlinks")
            streams = []
            for stream in manifest["streams"]:
                samples = []
                for sample in stream["samples"]:
                    payload = _read_file(asset_directory, sample["path"].split("/")[1])
                    shape = sample["shape"]
                    validate_payload(payload, shape, sample["payload_sha256"])
                    samples.append(
                        Sample(
                            sample["id"],
                            sample["ordinal"],
                            None
                            if sample["relative_time"] is None
                            else float(sample["relative_time"]),
                            sample["payload_sha256"],
                            payload,
                            tuple(shape) if shape is not None else None,
                            sample["provenance"],
                        )
                    )
                streams.append(
                    ObservationStream(
                        stream["id"],
                        stream["modality"],
                        stream["encoding"],
                        stream["source_id"],
                        tuple(samples),
                        tuple(Gap(**gap) for gap in stream["gaps"]),
                    )
                )
        finally:
            os.close(asset_directory)
    finally:
        os.close(directory)
    return Demonstration(
        manifest["source_id"],
        manifest["source_assistance"],
        tuple(manifest["consumers"]),
        tuple(streams),
        tuple(detached(manifest["commands"])) if manifest["commands"] is not None else None,
        tuple(detached(manifest["existing_facts"]))
        if manifest["existing_facts"] is not None
        else None,
        sha256(manifest_payload),
        manifest_payload,
    )
