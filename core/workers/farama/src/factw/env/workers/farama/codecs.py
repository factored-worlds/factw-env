from collections.abc import Mapping
from math import isfinite

import numpy as np
from gymnasium import spaces


def to_json(value):
    """Preserve native observation structure without lossy string coercions."""
    if isinstance(value, np.ndarray):
        return to_json(value.tolist())
    if isinstance(value, np.generic):
        return to_json(value.item())
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise ValueError("Observation mapping keys must be strings")
        return {key: to_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_json(item) for item in value]
    if value is None or type(value) in (str, bool, int):
        return value
    if type(value) is float and isfinite(value):
        return value
    raise ValueError(f"Value is not finite JSON data: {type(value).__name__}")


def _bounds(value, *, compact=True):
    array = np.asarray(value)
    if compact and array.size and np.all(array == array.flat[0]):
        array = np.asarray(array.flat[0])
    if array.ndim:
        return [_bounds(item, compact=False) for item in array]
    scalar = array.item()
    if np.isposinf(scalar):
        return "+infinity"
    if np.isneginf(scalar):
        return "-infinity"
    return to_json(scalar)


def describe_space(space):
    result = {"type": type(space).__name__}
    if isinstance(space, spaces.Dict):
        result["spaces"] = {key: describe_space(item) for key, item in space.spaces.items()}
    elif isinstance(space, spaces.Tuple):
        result["spaces"] = [describe_space(item) for item in space.spaces]
    elif isinstance(space, spaces.Discrete):
        result.update(n=int(space.n), start=int(space.start))
    elif isinstance(space, spaces.Box):
        result.update(
            shape=list(space.shape),
            dtype=str(space.dtype),
            low=_bounds(space.low),
            high=_bounds(space.high),
        )
    elif isinstance(space, spaces.MultiDiscrete):
        result.update(nvec=to_json(space.nvec), start=to_json(space.start), dtype=str(space.dtype))
    elif isinstance(space, spaces.MultiBinary):
        result.update(shape=list(space.shape), dtype=str(space.dtype))
    elif isinstance(space, spaces.Text):
        result.update(
            min_length=space.min_length,
            max_length=space.max_length,
            charset="".join(sorted(space.character_set)),
        )
        if type(space).__module__ == "miniwob.spaces" and type(space).__name__ == "Unicode":
            result["charset"] = "unicode"
    elif isinstance(space, spaces.Sequence):
        result.update(feature_space=describe_space(space.feature_space), stack=space.stack)
    else:
        raise TypeError(f"Unsupported space: {type(space).__name__}")
    return result


def decode_action(space, value):
    """Validate JSON actions before converting into the exact upstream type."""
    if isinstance(space, spaces.Dict):
        if not isinstance(value, dict) or value.keys() != space.spaces.keys():
            raise ValueError("Action dictionary keys must match the action space")
        action = {key: decode_action(item, value[key]) for key, item in space.spaces.items()}
    elif isinstance(space, spaces.Tuple):
        if not isinstance(value, list) or len(value) != len(space.spaces):
            raise ValueError("Action tuple length must match the action space")
        action = tuple(
            decode_action(item, val) for item, val in zip(space.spaces, value, strict=True)
        )
    elif isinstance(space, spaces.Discrete):
        if type(value) is not int:
            raise ValueError("Discrete actions must be integers")
        action = value
    elif isinstance(space, (spaces.Box, spaces.MultiDiscrete, spaces.MultiBinary)):
        raw = np.asarray(value)
        if raw.shape != space.shape or raw.dtype.kind not in "iuf":
            raise ValueError("Action must have the declared numeric shape")
        if not np.all(np.isfinite(raw)):
            raise ValueError("Action numbers must be finite")
        if space.dtype.kind in "iu" and not np.all(raw == np.floor(raw)):
            raise ValueError("Integer action spaces require integral values")
        if space.dtype.kind in "iu":
            limits = np.iinfo(space.dtype)
            if np.any(raw < limits.min) or np.any(raw > limits.max):
                raise ValueError("Action exceeds integer dtype bounds")
        if space.dtype.kind == "f":
            limit = np.finfo(space.dtype).max
            if np.any(raw < -limit) or np.any(raw > limit):
                raise ValueError("Action exceeds floating dtype bounds")
        action = raw.astype(space.dtype)
        if not np.all(np.isfinite(action)):
            raise ValueError("Action exceeds floating dtype bounds")
    elif isinstance(space, spaces.Text):
        action = value
    else:
        raise TypeError(f"Unsupported action space: {type(space).__name__}")
    if not space.contains(action):
        raise ValueError("Action lies outside the upstream action space")
    return action
