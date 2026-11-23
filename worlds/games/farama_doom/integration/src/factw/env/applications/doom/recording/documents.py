"""Archive the exact installed declarations used by a new agent run."""

import hashlib

from factw.env.worlds.doom.assets import document_bytes


def write_documents(output, scenario, *, planner=None):
    directory = output / "smsl"
    directory.mkdir()
    hashes = {}
    documents = document_bytes(scenario)
    if planner is not None:
        from ..runtime.documents import resolved_documents

        documents["system.smsl"] = resolved_documents(scenario, planner=planner)[
            "system.smsl"
        ].encode()
    for name, content in documents.items():
        (directory / name).write_bytes(content)
        hashes[name] = hashlib.sha256(content).hexdigest()
    return hashes
