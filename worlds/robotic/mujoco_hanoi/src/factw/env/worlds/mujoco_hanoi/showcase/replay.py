"""Index recorded board-camera frames by their native time and confirmed facts."""

import json
import webbrowser
from pathlib import Path

from .recording import RECORDING_SCHEMA


def replay_run(run, *, open_page=True):
    run = Path(run).resolve()
    if not (run / "report.json").is_file():
        raise ValueError("Choose a completed Robot Hanoi recording")
    report = json.loads((run / "report.json").read_text())
    if report["schema"] not in {"factw.hanoi-robot-recording/1", RECORDING_SCHEMA}:
        raise ValueError("Unrecognized Robot Hanoi recording format")
    timeline = []
    facts, changes, phase, placements = {}, {}, "ready", 0
    with (run / "events.jsonl").open(encoding="utf-8") as events:
        for line in events:
            event = json.loads(line)
            if "facts" in event:
                facts, changes = event["facts"], event.get("changes", {})
            match event["kind"]:
                case "request" if "facts" in event:
                    phase = "queued"
                case "control":
                    phase = event["phase"]
                case "placement":
                    phase = event["outcome"]
                    placements += 1
                case "failed":
                    phase = "failed"
                case "frame":
                    path = (run / event["path"]).resolve()
                    if not path.is_relative_to(run / "frames") or not path.is_file():
                        raise ValueError(f"Missing Robot Hanoi camera frame: {event['path']}")
                    timeline.append(
                        {
                            "image": path.relative_to(run).as_posix(),
                            "time": event["time"],
                            "camera": event["camera"],
                            "facts": facts,
                            "changes": changes,
                            "phase": phase,
                            "placements": placements,
                        }
                    )
    if not timeline or len(timeline) != report["frames"]:
        raise ValueError("The Robot Hanoi recording has incomplete camera evidence")
    data = json.dumps({"report": report, "timeline": timeline}).replace("<", "\\u003c")
    template = Path(__file__).with_name("replay.html").read_text(encoding="utf-8")
    output = run / "replay.html"
    output.write_text(template.replace("[[REPLAY_DATA]]", data), encoding="utf-8")
    if open_page:
        webbrowser.open(output.as_uri())
    return output
