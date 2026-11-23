from pathlib import Path

from factw.env.core.validation import require


def source_paths(records: list[dict], overrides: tuple[Path, ...] | None) -> tuple[Path, ...]:
    paths = (
        tuple(Path(record["path"]) for record in records)
        if overrides is None
        else tuple(Path(path) for path in overrides)
    )
    require(len(paths) == len(records), "Supply one exclusion path per recorded source, in order")
    return paths


def verify_source(actual: dict, recorded: dict, message: str) -> None:
    require({**actual, "path": recorded["path"]} == recorded, message)


def verify_exclusions(actual: dict, recorded: dict, message: str) -> None:
    require(len(actual["sources"]) == len(recorded["sources"]), message)
    for current, original in zip(actual["sources"], recorded["sources"], strict=True):
        verify_source(current, original, message)
    require({**actual, "sources": recorded["sources"]} == recorded, message)
