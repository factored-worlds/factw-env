import base64
from io import BytesIO

import numpy as np
from PIL import Image


def encode_sensors(rgb, depth, proprioception, depth_buffer, depth_buffer_encoding):
    if (depth_buffer is None) != (depth_buffer_encoding is None):
        raise ValueError("Depth buffer and encoding must be paired")
    if depth_buffer_encoding is not None and depth_buffer_encoding != "vizdoom-depth-u8-v1":
        raise ValueError("Unknown depth buffer encoding")
    if rgb is None:
        if depth is not None or proprioception is not None or depth_buffer is not None:
            raise ValueError("Sensors require RGB")
        return {
            "rgb": None,
            "depth": None,
            "proprioception": None,
            "depth_buffer": None,
            "depth_buffer_encoding": None,
        }
    if (
        not isinstance(rgb, np.ndarray)
        or rgb.dtype != np.uint8
        or rgb.ndim != 3
        or rgb.shape[2] != 3
        or min(rgb.shape[:2]) < 1
    ):
        raise ValueError("Observation RGB must be nonempty uint8 HWC")
    if depth is not None and (
        not isinstance(depth, np.ndarray)
        or depth.dtype.kind != "f"
        or depth.shape != rgb.shape[:2]
        or not np.isfinite(depth).all()
        or (depth < 0).any()
    ):
        raise ValueError("Depth must be finite nonnegative floats matching RGB")
    if depth_buffer is not None and (
        not isinstance(depth_buffer, np.ndarray)
        or depth_buffer.dtype != np.uint8
        or depth_buffer.shape != rgb.shape[:2]
    ):
        raise ValueError("Depth buffer must be uint8 matching RGB")
    if proprioception is not None and (
        not isinstance(proprioception, np.ndarray)
        or proprioception.dtype.kind not in "iuf"
        or proprioception.ndim != 1
        or proprioception.size == 0
        or not np.isfinite(proprioception).all()
    ):
        raise ValueError("Proprioception must be a nonempty finite real numeric vector")
    stream = BytesIO()
    Image.fromarray(rgb).save(stream, format="PNG")
    result = {"rgb": base64.b64encode(stream.getvalue()).decode("ascii")}
    for name, values in (
        ("depth", depth),
        ("proprioception", proprioception),
        ("depth_buffer", depth_buffer),
    ):
        result[name] = None
        if values is not None:
            stream = BytesIO()
            np.save(stream, values, allow_pickle=False)
            result[name] = base64.b64encode(stream.getvalue()).decode("ascii")
    result["depth_buffer_encoding"] = depth_buffer_encoding
    return result
