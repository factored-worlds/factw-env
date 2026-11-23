"""Publish synchronized human-play snapshots to a companion viewer."""

import json
import sys
from pathlib import Path

from PIL import Image


class LiveCapture:
    def __init__(self, directory):
        self.directory = Path(directory).resolve(strict=True)
        self.closed_marker = self.directory / "closed"
        self.stream = (self.directory / "samples.jsonl").open("x", buffering=1, encoding="utf-8")

    def close(self):
        self.stream.close()

    def start_episode(self, game, index):
        self.episode = index
        self.variables = tuple(game.get_available_game_variables())
        self.first_tic = None
        self.last_tic = -1

    def observe(self, game, *, terminal=False):
        if self.stream.closed or self.closed_marker.exists():
            self.close()
            return
        state = None if terminal else game.get_state()
        if state is None and not terminal:
            return
        try:
            self._publish(game, state, terminal)
        except (OSError, ValueError) as error:
            print(f"Doom live facts capture stopped: {error}", file=sys.stderr, flush=True)
            self.close()

    def _publish(self, game, state, terminal):
        native_tic = int(game.get_episode_time() if terminal else state.tic)
        if self.first_tic is None:
            self.first_tic = native_tic
        tic = native_tic - self.first_tic
        # The engine can reset its clock at an exit. Keep the raw value and
        # place the terminal telemetry after the last observed state.
        if terminal:
            tic = max(tic, self.last_tic + 1)
        elif tic <= self.last_tic:
            return

        values = (
            (game.get_game_variable(channel) for channel in self.variables)
            if terminal
            else state.game_variables
        )
        variables = {
            channel.name: float(value)
            for channel, value in zip(self.variables, values, strict=True)
        }
        frame = None
        if state is not None:
            frame = f"{self.episode:03d}-{tic:06d}.png"
            image = Image.fromarray(state.screen_buffer)
            image.thumbnail((400, 300), Image.Resampling.NEAREST)
            image.save(self.directory / frame, compress_level=1)
        row = {
            "episode": self.episode,
            "tic": tic,
            "native_tic": native_tic,
            "variables": variables,
            "terminal": terminal,
            "frame": frame,
        }
        self.stream.write(json.dumps(row, separators=(",", ":"), allow_nan=False) + "\n")
        self.last_tic = tic
