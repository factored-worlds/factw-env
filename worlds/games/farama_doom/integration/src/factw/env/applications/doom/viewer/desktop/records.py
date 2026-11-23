"""Read paired observations and State Language facts as a Doom agent writes them."""

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class LiveStep:
    index: int
    tic: int
    rgb: Path | None
    facts: dict[str, dict[str, object]]
    changes: dict[str, dict[str, tuple[object, object]]]
    command: dict | None
    skill: str | None
    episode: int = 0
    frame_status: str | None = None


def completed_json(path):
    try:
        data = path.read_bytes()
    except FileNotFoundError:
        return None
    # The recorder pretty-prints a JSON object. Its unindented closing brace
    # distinguishes a complete record from an interrupted multiline write.
    return json.loads(data) if data.endswith(b"\n}\n") else None


class LiveRecords:
    def __init__(self, run):
        self.run = Path(run).resolve()
        self.next_index = 0

    def poll(self):
        """Return the next complete row, or None while the writer is still working."""
        index = self.next_index
        episode = self.run / "episode"
        private = self.run / "privileged"
        frame = episode / f"observations/{index:06d}/rgb.png"

        if index == 0:
            # Initial state is written before EpisodeWriter saves its first frame.
            if completed_json(episode / "episode.json") is None:
                return None
            state = completed_json(private / "initial-inspection.json")
            if state is None:
                return None
            changes, command, skill = {}, None, None
            frame_status = state.get("frame_status")
        else:
            # Each step trace follows its completed observations. steps.jsonl is
            # buffered, so its last readable line can lag the live game.
            recorded = completed_json(private / f"step-{index:06d}.json")
            if recorded is None:
                return None
            state = recorded["inspection"]
            trace = recorded["trace"]
            before, after = trace["facts_before"], trace["facts_after"]
            changes = {}
            for group, facts in after.items():
                changed = {
                    key: (before[group][key], value)
                    for key, value in facts.items()
                    if before[group][key] != value
                }
                if changed:
                    changes[group] = changed
            command, skill = trace["command"], trace["skill"]
            frame_status = recorded.get("frame_status")

        self.next_index += 1
        return LiveStep(
            index,
            state["episode_tics"],
            frame if frame.is_file() else None,
            state["facts"],
            changes,
            command,
            skill,
            frame_status=frame_status,
        )
