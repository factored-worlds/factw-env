"""Build a local viewer in the owning Doom application environment."""

import argparse
import json
import shutil
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory

from factw.env.worlds.doom.assets import scenario_configuration
from factw.env.worlds.doom.native import recorded_mission_assets

from .symbolic_track import compile_track

HERE = Path(__file__).resolve().parent
MISSIONS = {
    "games.doom/retrieve-key-and-escape": "Key, Door, Exit",
    "games.doom/activate-reactor-and-extract": "Reactor and Extract",
}


def recording_input(recording, episode):
    report = json.loads((recording / "play-report.json").read_text())
    scenario = (report.get("selection") or {}).get("scenario")
    if report.get("mode") != "human-async-spectator" or scenario not in MISSIONS:
        raise ValueError("Select a human recording of Key, Door, Exit or Reactor and Extract")
    if not 0 <= episode < len(report["episodes"]):
        raise ValueError("Episode is outside the recorded range")
    entry = report["episodes"][episode]
    if not entry["demo_finalized"]:
        raise ValueError("This episode has no finalized Doom demo")
    demo = (recording / entry["demo"]).resolve(strict=True)
    if not demo.is_relative_to(recording):
        raise ValueError("Native demos must remain inside their recording directory")
    return report, scenario, demo, entry


def write_view(output, scenario, recording, entry, tracks):
    rows = tracks["frames"]
    if not rows or not any(row["frame"] for row in rows):
        raise ValueError("The replay did not deliver any RGB frames")
    for asset in ("index.html", "viewer.css", "viewer.js"):
        shutil.copyfile(HERE / asset, output / asset)
    data = {
        "title": MISSIONS[scenario],
        "recording": recording.name,
        "ticrate": tracks["ticrate"],
        "outcome": (
            "Died"
            if entry["dead"]
            else "Timed out"
            if entry["native_timeout"]
            else "Extracted"
            if entry["return"] == 1
            else {"interrupted": "Interrupted", "play_budget": "Play budget reached"}.get(
                entry["stop_reason"], "Run ended"
            )
        ),
        "frames": [
            {
                key: row.get(key)
                for key in ("tic", "native_tic", "frame", "facts", "changes", "variables", "action")
            }
            for row in rows
        ],
    }
    (output / "timeline.js").write_text(
        "window.doomReplay = " + json.dumps(data, ensure_ascii=True, allow_nan=False) + ";\n"
    )


def capture_view(recording, worker, output, episode):
    report, scenario, demo, entry = recording_input(recording, episode)
    with recorded_mission_assets(recording, report) as directory:
        config, _ = scenario_configuration(directory)
        subprocess.run(
            [
                str(worker),
                "-I",
                str(HERE / "native_capture.py"),
                "--report",
                str(recording / "play-report.json"),
                "--demo",
                str(demo),
                "--config",
                config["config_path"],
                "--output",
                str(output),
                "--episode",
                str(episode),
            ],
            cwd=output,
            check=True,
        )
    tracks, world = compile_track(json.loads((output / "captures.json").read_text()))
    (output / "symbolic_tracks.json").write_text(json.dumps(tracks, allow_nan=False) + "\n")
    (output / "world.json").write_text(world.to_json() + "\n")
    write_view(output, scenario, recording, entry, tracks)


def build(recording, worker, output, episode=0):
    """Write a new portable frame-and-facts view for a native human demo."""
    recording, output = Path(recording).resolve(), Path(output).resolve()
    worker = Path(worker).absolute()
    if output.exists():
        raise FileExistsError(f"Replay view already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix=".doom_inspection_", dir=output.parent) as scratch:
        view = Path(scratch)
        capture_view(recording, worker, view, episode)
        output.mkdir()
        index = view / "index.html"
        for asset in view.iterdir():
            if asset != index:
                asset.rename(output / asset.name)
        index.rename(output / index.name)
    return output / "index.html"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("recording", "worker", "output"):
        parser.add_argument(name, type=Path)
    parser.add_argument("episode", nargs="?", default=0, type=int)
    args = parser.parse_args()
    build(args.recording, args.worker, args.output, args.episode)
