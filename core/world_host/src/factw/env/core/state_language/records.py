"""Lossless JSON payloads inside the stable State Language value profile."""

import hashlib
import json

from factw.env.core.json_values import copy_json


def encode(value):
    return {"json": json.dumps(copy_json(value), allow_nan=False, separators=(",", ":"))}


def decode(value):
    from factw.env.core.recording.jsonio import json_value

    if type(value) is not dict or set(value) != {"json"} or type(value["json"]) is not str:
        raise ValueError("Expected an engines JSON payload")
    return json_value(value["json"])


def describe(result):
    observation = result.observation
    sensors = {}
    for name in ("rgb", "depth", "proprioception", "depth_buffer"):
        array = getattr(observation, name)
        if array is not None:
            sensors[name] = {
                "shape": list(array.shape),
                "dtype": str(array.dtype),
                "sha256": hashlib.sha256(array.tobytes()).hexdigest(),
                **(
                    {"encoding": observation.depth_buffer_encoding}
                    if name == "depth_buffer"
                    else {}
                ),
            }
    return {
        "observation": {
            "text": observation.text,
            "structured": observation.structured,
            "sensors": sensors,
        },
        "reward": result.reward,
        "terminated": result.terminated,
        "truncated": result.truncated,
        "outcome": result.outcome,
        "elapsed_seconds": result.elapsed_seconds,
    }
