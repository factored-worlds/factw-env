"""The worker side of the lockstep Doom recorder's mapped RGB slot."""

from mmap import mmap
from struct import Struct

import numpy as np

HEADER = Struct("!QII")


class RecordingRgb:
    def __init__(self, path, resources):
        source = resources.enter_context(open(path, "r+b"))
        self._slot = resources.enter_context(mmap(source.fileno(), 0))

    def publish(self, tic, rgb):
        pixels = np.ascontiguousarray(rgb)
        height, width, channels = pixels.shape
        if (
            channels != 3
            or pixels.dtype != np.uint8
            or len(self._slot) != HEADER.size + pixels.nbytes
        ):
            raise ValueError("Doom RGB does not fit the configured recording slot")
        self._slot[HEADER.size :] = memoryview(pixels).cast("B")
        HEADER.pack_into(self._slot, 0, tic, width, height)
