from pathlib import Path

from factw.env.core.recording.contract import read_records
from factw.env.core.recording.jsonio import asset_path

PUBLIC_FILES_VERSION = "trajectory-public-v1"


def public_files(path: str | Path) -> tuple[str, ...]:
    root = Path(path)
    metadata, rows = read_records(root)
    paths = {"episode.json", "steps.jsonl", *metadata["initial_observation"].values()}
    for row in rows:
        paths.update(row["observation"].values())
    for relative in paths:
        if not asset_path(root, relative).is_file():
            raise FileNotFoundError(root / relative)
    return tuple(sorted(paths))
