"""Play native Doom inside a window with live State Language facts."""

import argparse
import json
import os
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from ..replay.symbolic_track import ObservationTrack
from .records import LiveStep, completed_json
from .runner import follow


class HumanRecords:
    def __init__(self, directory, scenario, run):
        self.directory = directory
        self.scenario = scenario
        self.run = run
        self.stream = None
        self.track = None
        self.episode = None
        self.next_index = 0

    def poll(self):
        if self.stream is None:
            try:
                self.stream = (self.directory / "samples.jsonl").open("rb")
            except FileNotFoundError:
                return None
        offset = self.stream.tell()
        line = self.stream.readline()
        if not line.endswith(b"\n"):
            self.stream.seek(offset)
            return None
        row = json.loads(line)
        if row["episode"] != self.episode:
            self.episode = row["episode"]
            self.track = ObservationTrack(
                self.scenario, f"{self.run.name}/{self.episode}", source="live"
            )
        projected = self.track.observe(row)
        facts, changes = {}, {}
        for name, value in projected["facts"].items():
            branch, fact = name.split(".", 1)
            facts.setdefault(branch, {})[fact] = value
        for name, change in projected["changes"].items():
            branch, fact = name.split(".", 1)
            changes.setdefault(branch, {})[fact] = change["before"], change["after"]
        step = LiveStep(
            index=self.next_index,
            tic=row["tic"],
            rgb=self.directory / row["frame"] if row["frame"] else None,
            facts=facts,
            changes=changes,
            command=None,
            skill=None,
            episode=row["episode"],
        )
        self.next_index += 1
        return step

    def close(self):
        if self.stream is not None:
            self.stream.close()


def play(output, scenario, native):
    parser = argparse.ArgumentParser(add_help=False, allow_abbrev=False)
    parser.add_argument("--resolution")
    options, _ = parser.parse_known_args(native)

    def completion():
        report = completed_json(output / "play-report.json")
        if report is None:
            raise ValueError("Doom finished without a play report")
        last = report["episodes"][-1] if report["episodes"] else {}
        if last.get("demo_finalized"):
            return "Recording saved"
        return "Doom play ended"

    print("Doom player: keyboard and mouse with live SMSL facts.", flush=True)
    with TemporaryDirectory(prefix="fw-doom-live-") as scratch:
        directory = Path(scratch)
        records = HumanRecords(directory, scenario, output)
        try:
            return follow(
                native,
                records,
                completion,
                human=True,
                environment={**os.environ, "FACTW_DOOM_LIVE_CAPTURE": scratch},
                game_resolution=options.resolution,
            )
        finally:
            records.close()


if __name__ == "__main__":
    raise SystemExit(play(Path(sys.argv[1]), sys.argv[2], sys.argv[3:]))
