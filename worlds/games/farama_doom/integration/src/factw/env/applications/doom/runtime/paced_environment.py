"""An independent 35 Hz host clock for single-tic ViZDoom PLAYER commands."""

import asyncio
from collections import Counter, deque
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from threading import Condition
from time import monotonic

PERIOD = 1 / 35
CAPTURE_CAPACITY = 64
FRAME_CAPACITY = 8


class PacedEnvironment:
    def __init__(self, native, capture, *, max_steps):
        self._native, self._capture, self._max_steps = native, capture, max_steps
        self.metadata = native.metadata
        self.terminated = self.truncated = False
        self._condition = Condition()
        self._records = deque()
        self._pending = None
        self._issued_tic = self._consumed_tic = None
        self._stopping = False
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="doom-clock")
        self._task = None
        self._command_states = Counter()
        self._queued_frames = self._peak_captures = self._peak_frames = 0
        self._cadence = None
        self.frame = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.close()

    def reset(self, *, seed):
        if self._issued_tic is not None:
            raise RuntimeError("A paced Doom environment owns one episode")
        observation = self._native.reset(seed=seed)
        self.terminated, self.truncated = self._native.terminated, self._native.truncated
        self._issued_tic = self._consumed_tic = observation.structured["episode_tics"]
        self._capture_seconds = monotonic()
        return observation

    def apply(self, command):
        """Submit the command for the next tic and observe the next native result."""
        with self._condition:
            if self._issued_tic is None or self.terminated or self.truncated or self._stopping:
                raise RuntimeError("Reset before applying paced Doom control")
            if self._task is not None and self._task.done() and not self._records:
                self._task.result()
                raise RuntimeError("Paced Doom has no remaining native captures")
            if self._consumed_tic == self._issued_tic:
                self._pending = (self._consumed_tic, monotonic(), command)
                submission = "queued"
            else:
                submission = "capture_no_longer_current"
            if self._task is None:
                self._task = self._executor.submit(asyncio.run, self._run())
                self._task.add_done_callback(self._wake)
            self._condition.wait_for(lambda: self._records or self._task.done())
            if not self._records:
                self._task.result()
                raise RuntimeError("Paced Doom stopped before the requested capture")
            applied, result, pacing, self.frame = self._records.popleft()
            if self.frame[0] is not None:
                self._queued_frames -= 1
            self._consumed_tic = pacing["target_tic"]
            self.terminated, self.truncated = result.terminated, result.truncated
        return applied, result, {**pacing, "requested_command": command, "submission": submission}

    def _wake(self, _):
        with self._condition:
            self._condition.notify_all()

    async def _run(self):
        from smsl_runtime import Periodic, TimingProfile
        from smsl_runtime.metrics import Cadence

        profile = TimingProfile(period=PERIOD, deadline=PERIOD, max_age=PERIOD)
        with closing(Periodic(profile)) as schedule, closing(Cadence(self._max_steps)) as cadence:
            await self._pace(schedule, cadence)

    async def _pace(self, schedule, cadence):
        expected = 0
        try:
            while True:
                release = await schedule.next()
                with self._condition:
                    if self._stopping:
                        return
                    if len(self._records) >= CAPTURE_CAPACITY:
                        raise RuntimeError("Paced Doom could not retain another native capture")
                    source = self._issued_tic
                    target = self._issued_tic = source + 1
                    pending, self._pending = self._pending, None
                    frame_space = self._queued_frames < FRAME_CAPACITY
                started = monotonic()
                submitted = None if pending is None else pending[1]
                if pending is None:
                    state, command = "neutral_missing", {"buttons": {}}
                elif pending[0] != source:
                    raise RuntimeError("Paced Doom accepted a command for a different native tic")
                elif submitted > release.scheduled or release.skipped or started > release.deadline:
                    state, command = "neutral_expired", {"buttons": {}}
                else:
                    state, command = "agent", pending[2]
                age = started - self._capture_seconds if state == "agent" else None
                result = self._native.step(command)
                captured = monotonic()
                if (
                    result.observation.structured["episode_tics"] != target
                    or result.elapsed_seconds != PERIOD
                ):
                    raise RuntimeError("Paced Doom expected exactly one applied native tic")
                image, status = self._capture.record(result.observation, frame_space=frame_space)
                if status == "recorder_overload":
                    status = "capture_queue_overload"
                finished = monotonic()
                pacing = {
                    "source_tic": source,
                    "target_tic": target,
                    "release_index": release.index,
                    "scheduled_seconds": release.scheduled,
                    "started_seconds": started,
                    "finished_seconds": finished,
                    "skipped_releases": release.skipped,
                    "command_state": state,
                    "submitted_seconds": submitted,
                    "captured_seconds": captured,
                    "source_capture_seconds": self._capture_seconds,
                }
                self._capture_seconds = captured
                cadence.record(release, finished=finished, output_age=age)
                expected = release.index + 1
                with self._condition:
                    self._command_states[state] += 1
                    self._records.append((command, result, pacing, (image.rgb, status)))
                    self._queued_frames += image.rgb is not None
                    self._peak_captures = max(self._peak_captures, len(self._records))
                    self._peak_frames = max(self._peak_frames, self._queued_frames)
                    self._condition.notify_all()
                if result.terminated or result.truncated:
                    return
        finally:
            self._cadence = cadence.summary(expected_releases=expected)

    def close(self):
        with self._condition:
            self._stopping = True
        self._executor.shutdown()

    def finish(self):
        self.close()
        if self._task is None:
            raise RuntimeError("Paced Doom finished without applying a native tic")
        self._task.result()
        if self._records:
            raise RuntimeError("Paced Doom ended with undelivered native transitions")
        return {
            "profile": "doom-bridge-paced-player-v1",
            "period_seconds": PERIOD,
            "cadence": self._cadence,
            "command_states": dict(self._command_states),
            "capture_capacity": CAPTURE_CAPACITY,
            "peak_captures": self._peak_captures,
            "frame_capacity": FRAME_CAPACITY,
            "peak_frames": self._peak_frames,
        }
