import numpy as np
from factw.env.core.recording.jsonio import asset_path
from factw.env.core.recording.versions import DEPTH_BUFFER_ENCODING
from PIL import Image

SENSOR_NAMES = ("rgb", "depth", "proprioception", "depth_buffer")


def validate_sensors(
    rgb, depth=None, proprioception=None, *, depth_buffer=None, depth_buffer_encoding=None
):
    if (
        not isinstance(rgb, np.ndarray)
        or rgb.dtype != np.uint8
        or rgb.ndim != 3
        or rgb.shape[2] != 3
        or min(rgb.shape[:2]) < 1
    ):
        raise ValueError("RGB must be a nonempty uint8 array with shape (height, width, 3)")
    if depth is not None and (
        not isinstance(depth, np.ndarray)
        or depth.dtype.kind != "f"
        or depth.shape != rgb.shape[:2]
        or not np.isfinite(depth).all()
        or (depth < 0).any()
    ):
        raise ValueError("Depth must be finite nonnegative floats matching RGB height/width")
    if proprioception is not None and (
        not isinstance(proprioception, np.ndarray)
        or proprioception.dtype.kind not in "iuf"
        or proprioception.ndim != 1
        or proprioception.size == 0
        or not np.isfinite(proprioception).all()
    ):
        raise ValueError("Proprioception must be a nonempty finite real numeric vector")
    if depth_buffer is None:
        if depth_buffer_encoding is not None:
            raise ValueError("Depth buffer encoding requires a buffer")
    elif (
        not isinstance(depth_buffer, np.ndarray)
        or depth_buffer.dtype != np.uint8
        or depth_buffer.shape != rgb.shape[:2]
        or depth_buffer_encoding != DEPTH_BUFFER_ENCODING
    ):
        raise ValueError(
            "Depth buffer must be uint8 matching RGB with encoding vizdoom-depth-u8-v1"
        )


def sensor_paths(folder, observation):
    return {
        name: f"{folder}/{name}.{'png' if name == 'rgb' else 'npy'}"
        for name in SENSOR_NAMES
        if getattr(observation, name) is not None
    }


def save_sensors(root, paths, observation):
    if "rgb" in paths:
        Image.fromarray(observation.rgb).save(root / paths["rgb"], format="PNG")
    for name in ("depth", "proprioception", "depth_buffer"):
        if name in paths:
            np.save(root / paths[name], getattr(observation, name), allow_pickle=False)


def load_sensors(root, paths):
    values = {}
    if "rgb" in paths:
        with Image.open(asset_path(root, paths["rgb"])) as image:
            if image.format != "PNG" or image.mode != "RGB":
                raise ValueError("RGB assets must be actual RGB PNG images")
            values["rgb"] = np.array(image)
    for name in ("depth", "proprioception", "depth_buffer"):
        if name in paths:
            with asset_path(root, paths[name]).open("rb") as stream:
                values[name] = np.lib.format.read_array(stream, allow_pickle=False)
    return values
