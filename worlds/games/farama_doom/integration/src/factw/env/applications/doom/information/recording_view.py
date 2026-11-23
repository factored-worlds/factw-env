"""Detached declared native observations for the recorder, separate from agent views."""

from dataclasses import replace
from math import isfinite

import numpy as np
from factw.env.core.core import AgentObservation
from factw.env.core.recording.assets import validate_observation
from factw.env.core.recording.versions import (
    DEPTH_BUFFER_ENCODING,
)
from factw.env.core.recording.versions import (
    sensor_encodings as validate_encodings,
)

NATIVE_FIELDS = (
    "episode_tics",
    "upstream_episode_tics",
    "sensor_available",
    "state_number",
)
LABEL_FIELDS = ("id", "name", "category", "bbox", "position", "angle")


class RecordingView:
    def __init__(self, configuration, *, sensor_encodings):
        if type(configuration) is not dict:
            raise ValueError("Doom recorder configuration must be an object")
        variables = configuration.get("public_game_variables", [])
        if type(variables) is not list or any(type(name) is not str for name in variables):
            raise ValueError("Doom recorder variables must be declared names")
        self.variables = tuple(dict.fromkeys(variables))
        self.labels = configuration.get("public_labels", False)
        self.depth = configuration.get("depth", False)
        if type(self.labels) is not bool or type(self.depth) is not bool:
            raise ValueError("Doom recorder channels must be Boolean declarations")
        self.sensor_encodings = validate_encodings("2.0", sensor_encodings)
        expected = {"depth_buffer": DEPTH_BUFFER_ENCODING} if self.depth else {}
        if self.sensor_encodings != expected:
            raise ValueError("Doom recorder depth must match its declared sensor encoding")

    def observation(self, observation):
        if not isinstance(observation, AgentObservation):
            raise TypeError("Doom recorder requires a native agent observation")
        structured = {}
        for name, value in observation.structured.items():
            if name in NATIVE_FIELDS:
                if name == "sensor_available":
                    if type(value) is not bool:
                        raise ValueError("Doom recorder sensor availability must be Boolean")
                elif type(value) is not int or value < 0:
                    raise ValueError("Doom recorder native counters must be nonnegative integers")
                structured[name] = value
            elif name == "game_variables":
                if type(value) is not dict:
                    raise ValueError("Doom recorder game_variables must be an object")
                structured[name] = {
                    key: item for key, item in value.items() if key in self.variables
                }
                if any(
                    item is not None and not _finite(item) for item in structured[name].values()
                ):
                    raise ValueError("Doom recorder game variables must be finite numbers or null")
            elif name == "labels" and self.labels:
                if value is not None and (
                    type(value) is not list or any(type(label) is not dict for label in value)
                ):
                    raise ValueError("Doom recorder labels must be an array of objects or null")
                structured[name] = (
                    None
                    if value is None
                    else [
                        {key: item for key, item in label.items() if key in LABEL_FIELDS}
                        for label in value
                    ]
                )
                for label in structured[name] or []:
                    _validate_label(label)
        result = AgentObservation(
            structured=structured,
            rgb=_pixels(observation.rgb),
            depth_buffer=(_pixels(observation.depth_buffer) if self.depth else None),
            depth_buffer_encoding=observation.depth_buffer_encoding if self.depth else None,
        )
        validate_observation(result)
        return result

    def transition(self, result):
        return replace(result, observation=self.observation(result.observation))

    def describe(self):
        return {
            "scope": "recording-only",
            "structured_fields": [*NATIVE_FIELDS, "game_variables"]
            + (["labels"] if self.labels else []),
            "game_variables": list(self.variables),
            "label_fields": list(LABEL_FIELDS) if self.labels else [],
            "sensors": ["rgb"] + (["depth_buffer"] if self.depth else []),
            "sensor_encodings": dict(self.sensor_encodings),
            "text": False,
            "private_inspection": "separate-privileged-output",
        }


def _pixels(value):
    if value is None:
        return None
    if not isinstance(value, np.ndarray):
        raise ValueError("Doom recorder sensors require NumPy arrays")
    return value.copy()


def _finite(value):
    return type(value) in (int, float) and isfinite(value)


def _validate_label(label):
    for name, value in label.items():
        if name == "id":
            valid = type(value) is int
        elif name in ("name", "category"):
            valid = type(value) is str
        elif name == "angle":
            valid = _finite(value)
        else:
            valid = (
                type(value) is list
                and len(value) == (4 if name == "bbox" else 3)
                and all(_finite(item) for item in value)
            )
        if not valid:
            raise ValueError(f"Doom recorder label {name} has an invalid native value")
