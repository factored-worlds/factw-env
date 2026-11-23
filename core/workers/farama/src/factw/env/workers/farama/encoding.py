import json
from math import isfinite

from .sensors import encode_sensors
from .types import Observation, Transition


def object_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON field: {key}")
        result[key] = value
    return result


def json_object(value: str) -> dict:
    result = json.loads(value, object_pairs_hook=object_pairs)
    if type(result) is not dict:
        raise ValueError("Expected a JSON object")
    json.dumps(result, allow_nan=False, ensure_ascii=False).encode("utf-8")
    return result


def observation(value: Observation) -> dict:
    if not isinstance(value, Observation):
        raise TypeError("Backend must return an Observation")
    if type(value.text) is not str or type(value.structured) is not dict:
        raise ValueError("Observation requires text and a structured JSON object")
    result = {
        "text": value.text,
        "structured": value.structured,
        **encode_sensors(
            value.rgb,
            value.depth,
            value.proprioception,
            value.depth_buffer,
            value.depth_buffer_encoding,
        ),
    }
    json.dumps(result, allow_nan=False, ensure_ascii=False).encode("utf-8")
    return result


def transition(value: Transition) -> dict:
    if not isinstance(value, Transition):
        raise TypeError("Backend must return a Transition")
    if type(value.reward) not in (float, int) or not isfinite(value.reward):
        raise ValueError("Reward must be finite")
    if type(value.terminated) is not bool or type(value.truncated) is not bool:
        raise ValueError("Episode boundaries must be Boolean")
    if type(value.outcome) is not str or not value.outcome:
        raise ValueError("Outcome must be nonempty text")
    if (
        type(value.elapsed_seconds) not in (float, int)
        or not isfinite(value.elapsed_seconds)
        or value.elapsed_seconds < 0
    ):
        raise ValueError("Elapsed time must be finite and nonnegative")
    return {
        "observation": observation(value.observation),
        "elapsed_seconds": value.elapsed_seconds,
        "reward": value.reward,
        "terminated": value.terminated,
        "truncated": value.truncated,
        "outcome": value.outcome,
    }
