from dataclasses import dataclass, field

import numpy as np


@dataclass(frozen=True)
class Observation:
    text: str = ""
    structured: dict = field(default_factory=dict)
    rgb: np.ndarray | None = None
    depth: np.ndarray | None = None
    proprioception: np.ndarray | None = None
    depth_buffer: np.ndarray | None = None
    depth_buffer_encoding: str | None = None


@dataclass(frozen=True)
class Transition:
    observation: Observation
    reward: float = 0.0
    terminated: bool = False
    truncated: bool = False
    outcome: str = "running"
    elapsed_seconds: float = 0.0
