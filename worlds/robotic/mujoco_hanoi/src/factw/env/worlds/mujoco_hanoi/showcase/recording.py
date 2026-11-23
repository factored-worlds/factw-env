"""Save the player camera and native controls on one simulation clock."""

import json
from pathlib import Path

from PIL import Image

RECORDING_SCHEMA = "factw.hanoi-robot-recording/2"


class Recording:
    def __init__(self, output):
        self.output = Path(output).absolute()
        self.output.mkdir(parents=True, exist_ok=False)
        self.frames = 0
        self.controls = 0
        self._events = (self.output / "events.jsonl").open("x", encoding="utf-8", buffering=1)

    def event(self, kind, time, **data):
        self._events.write(json.dumps({"kind": kind, "time": time, **data}, allow_nan=False) + "\n")

    def control(self, sample, **update):
        self.event(
            "control",
            sample.time,
            phase=sample.phase,
            actuator_targets=sample.control,
            grasped=sample.grasped,
            **update,
        )
        self.controls += 1

    def frame(self, rgb, camera, time):
        path = self.output / "frames" / f"{self.frames:06d}.jpg"
        path.parent.mkdir(exist_ok=True)
        Image.fromarray(rgb).save(path, quality=88)
        self.event("frame", time, camera=camera, path=path.relative_to(self.output).as_posix())
        self.frames += 1

    def finish(self, report, smsl_archive):
        self._events.close()
        (self.output / "smsl.json").write_text(smsl_archive, encoding="utf-8")
        pending = self.output / ".report.json"
        pending.write_text(
            json.dumps(
                {
                    "schema": RECORDING_SCHEMA,
                    "timebase": "mujoco-simulation-seconds",
                    "frames": self.frames,
                    "controls": self.controls,
                    **report,
                },
                indent=2,
                allow_nan=False,
            )
            + "\n",
            encoding="utf-8",
        )
        pending.replace(self.output / "report.json")
