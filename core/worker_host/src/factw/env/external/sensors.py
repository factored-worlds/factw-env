import base64
from io import BytesIO

import numpy as np
from PIL import Image


def decode_sensors(payload):
    values = {}
    for name in ("rgb", "depth", "proprioception", "depth_buffer"):
        encoded = payload[name]
        values[name] = None
        if encoded is None:
            continue
        if type(encoded) is not str:
            raise ValueError(f"Benchmark {name} must be a base64 string")
        data = BytesIO(base64.b64decode(encoded, validate=True))
        if name == "rgb":
            with Image.open(data) as image:
                if image.format != "PNG" or image.mode != "RGB":
                    raise ValueError("Benchmark RGB must be an RGB PNG image")
                values[name] = np.array(image)
        else:
            values[name] = np.lib.format.read_array(data, allow_pickle=False)
    values["depth_buffer_encoding"] = payload["depth_buffer_encoding"]
    return values
