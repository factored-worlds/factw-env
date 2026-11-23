"""Serialize explicitly described RGB bytes as lossless PNG API inputs."""

import base64
import hashlib
import json
import struct
import zlib


def encoded(value):
    return json.dumps(
        value, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":")
    ).encode("utf-8")


def _chunk(kind, data):
    return struct.pack("!I", len(data)) + kind + data + struct.pack("!I", zlib.crc32(kind + data))


def _png(rgb, width, height):
    row_size = width * 3
    rows = b"".join(
        b"\0" + rgb[offset : offset + row_size] for offset in range(0, len(rgb), row_size)
    )
    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", struct.pack("!2I5B", width, height, 8, 2, 0, 0, 0))
        + _chunk(b"IDAT", zlib.compress(rows))
        + _chunk(b"IEND", b"")
    )


def image_inputs(payload, assets):
    descriptors = payload.get("images", [])
    if not isinstance(descriptors, list) or len(descriptors) > 128:
        raise ValueError("At most 128 explicit RGB image descriptors are supported")
    seen = set()
    content = []
    text_bytes = 0
    image_tokens = 0
    pngs = {}
    for descriptor in descriptors:
        if not isinstance(descriptor, dict) or descriptor.get("encoding") != "rgb_uint8_hwc":
            raise ValueError("Only explicit rgb_uint8_hwc images are supported")
        asset_id = descriptor.get("asset_id")
        if not isinstance(asset_id, str) or not asset_id or asset_id in seen:
            raise ValueError("RGB image asset identities must be nonempty and unique")
        seen.add(asset_id)
        shape = descriptor.get("shape")
        if (
            not isinstance(shape, list)
            or len(shape) != 3
            or shape[2] != 3
            or any(type(value) is not int or value <= 0 for value in shape)
        ):
            raise ValueError("RGB shape must contain positive integer H,W,3")
        height, width, _ = shape
        patches = min(2500, ((width + 31) // 32) * ((height + 31) // 32))
        image_tokens += (patches * 6 + 4) // 5 + 1
        rgb = assets.get(asset_id)
        if type(rgb) is not bytes or len(rgb) != height * width * 3:
            raise ValueError("RGB image bytes must match the declared shape")
        if descriptor.get("sha256") != hashlib.sha256(rgb).hexdigest():
            raise ValueError("RGB image hash mismatch")
        png = _png(rgb, width, height)
        pngs[asset_id] = png
        label = encoded(descriptor).decode("utf-8")
        text_bytes += len(label.encode("utf-8"))
        content.extend(
            (
                {"type": "input_text", "text": label},
                {
                    "type": "input_image",
                    "detail": "high",
                    "image_url": ("data:image/png;base64," + base64.b64encode(png).decode("ascii")),
                },
            )
        )
    if set(assets) != seen:
        raise ValueError("Only and all explicitly declared RGB image assets may be supplied")
    return content, text_bytes, image_tokens, pngs
