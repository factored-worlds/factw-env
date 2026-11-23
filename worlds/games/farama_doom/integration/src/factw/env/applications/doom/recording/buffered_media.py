"""Read the lockstep RGB slot and drain a bounded recording queue."""

import re
from collections import Counter, deque
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import replace
from mmap import ACCESS_READ, mmap
from pathlib import Path
from struct import Struct
from tempfile import TemporaryDirectory

import numpy as np
from factw.env.external.collect import save

HEADER = Struct("!QII")
FRAME_CAPACITY = 8
RECORD_CAPACITY = 256


class Capture:
    def __init__(self, resources, resolution):
        match = re.fullmatch(r"RES_(\d+)X(\d+)", resolution)
        if match is None:
            raise ValueError("Buffered Doom recording needs a native WxH resolution")
        self.width, self.height = map(int, match.groups())
        if not (1 <= self.width <= 4096 and 1 <= self.height <= 4096):
            raise ValueError("Buffered Doom recording resolution exceeds the slot limit")
        self.path = Path(resources.enter_context(TemporaryDirectory(prefix="factw-doom-rgb-")))
        self.path /= "frame"
        file = resources.enter_context(self.path.open("x+b"))
        file.truncate(HEADER.size + self.width * self.height * 3)
        self._slot = resources.enter_context(mmap(file.fileno(), 0, access=ACCESS_READ))

    def record(self, observation, *, frame_space=True):
        if not observation.structured["sensor_available"]:
            return observation, "simulator_unavailable"
        if not frame_space:
            return observation, "recorder_overload"
        expected = observation.structured["episode_tics"], self.width, self.height
        if HEADER.unpack_from(self._slot) != expected:
            raise ValueError("Doom RGB slot does not match the native observation")
        rgb = np.ndarray(
            (self.height, self.width, 3), dtype=np.uint8, buffer=self._slot, offset=HEADER.size
        ).copy()
        return replace(observation, rgb=rgb), "recorded"


class Recorder:
    def __init__(self, writer, private, capture, initial_frame_status):
        self._writer, self._private, self._capture = writer, private, capture
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="doom-recorder")
        self._pending = deque()
        self._frames_pending = 0
        self._statuses = Counter({initial_frame_status: 1})
        self._peak_records = self._peak_frames = 0

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.finish()

    def finish(self):
        self._pool.shutdown()
        self._collect()

    def _collect(self):
        while self._pending and self._pending[0][0].done():
            job, recorded = self._pending.popleft()
            self._frames_pending -= recorded
            job.result()

    def append(self, index, command, result, entry, *, frame=None):
        self._collect()
        if len(self._pending) >= RECORD_CAPACITY:
            raise RuntimeError("Doom recorder could not retain every semantic transition")
        frame_space = self._frames_pending < FRAME_CAPACITY
        if frame is None:
            observation, status = self._capture.record(result.observation, frame_space=frame_space)
        else:
            rgb, status = frame
            if not frame_space and rgb is not None:
                rgb, status = None, "recorder_overload"
            observation = replace(result.observation, rgb=rgb)
        record = deepcopy(entry)
        record["frame_status"] = status
        predecessor = self._pending[-1][0] if self._pending else None
        job = self._pool.submit(
            self._write,
            predecessor,
            index,
            deepcopy(command),
            replace(result, observation=observation),
            record,
        )
        recorded = status == "recorded"
        self._pending.append((job, recorded))
        self._frames_pending += recorded
        self._statuses[status] += 1
        self._peak_records = max(self._peak_records, len(self._pending))
        self._peak_frames = max(self._peak_frames, self._frames_pending)

    def _write(self, predecessor, index, command, result, record):
        if predecessor is not None:
            predecessor.result()
        self._writer.append(command, result)
        save(self._private / f"step-{index:06d}.json", record)

    def summary(self):
        return {
            "transport": "lockstep-rgb-slot-v1",
            "frame_capacity": FRAME_CAPACITY,
            "record_capacity": RECORD_CAPACITY,
            "peak_frames": self._peak_frames,
            "peak_records": self._peak_records,
            "frames": {
                "recorded": 0,
                "recorder_overload": 0,
                "simulator_unavailable": 0,
                **self._statuses,
            },
        }
