from dataclasses import dataclass, field

import numpy as np
from factw.env.core.json_values import copy_json


@dataclass(frozen=True)
class Observation:
    rgb: np.ndarray
    depth: np.ndarray | None = None
    proprioception: np.ndarray | None = None
    depth_buffer: np.ndarray | None = None
    depth_buffer_encoding: str | None = None


@dataclass(frozen=True)
class GraphObservation:
    graph: dict
    tool_result: dict

    def __post_init__(self):
        for name in ("graph", "tool_result"):
            value = getattr(self, name)
            if type(value) is not dict:
                raise TypeError(f"{name} must be a JSON object")
            object.__setattr__(self, name, copy_json(value))


@dataclass(frozen=True)
class AgentObservation:
    text: str = ""
    structured: dict = field(default_factory=dict)
    rgb: np.ndarray | None = None
    depth: np.ndarray | None = None
    proprioception: np.ndarray | None = None
    depth_buffer: np.ndarray | None = None
    depth_buffer_encoding: str | None = None

    def __post_init__(self):
        if type(self.text) is not str or type(self.structured) is not dict:
            raise ValueError("Agent observations require text and a structured JSON object")
        self.text.encode("utf-8")
        object.__setattr__(self, "structured", copy_json(self.structured))


@dataclass(frozen=True)
class StepResult:
    observation: Observation | GraphObservation | AgentObservation
    reward: float
    terminated: bool
    truncated: bool
    elapsed_seconds: float
    outcome: str
