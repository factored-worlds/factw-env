from factw.env.core.core import AgentObservation, StepResult
from factw.env.core.recording.assets import validate_observation
from factw.env.core.recording.contract import number, text
from factw.env.external.sensors import decode_sensors


def result(value: dict) -> StepResult:
    if set(value) != {
        "observation",
        "reward",
        "terminated",
        "truncated",
        "outcome",
        "elapsed_seconds",
    }:
        raise ValueError("Invalid benchmark transition fields")
    payload = value["observation"]
    if type(payload) is not dict or set(payload) != {
        "text",
        "structured",
        "rgb",
        "depth",
        "proprioception",
        "depth_buffer",
        "depth_buffer_encoding",
    }:
        raise ValueError("Invalid benchmark observation fields")
    observed = AgentObservation(payload["text"], payload["structured"], **decode_sensors(payload))
    validate_observation(observed)
    number(value["reward"], "Benchmark reward")
    number(value["elapsed_seconds"], "Benchmark elapsed time", nonnegative=True)
    text(value["outcome"], "Benchmark outcome")
    if type(value["terminated"]) is not bool or type(value["truncated"]) is not bool:
        raise ValueError("Benchmark boundaries must be Boolean")
    return StepResult(
        observed,
        value["reward"],
        value["terminated"],
        value["truncated"],
        value["elapsed_seconds"],
        value["outcome"],
    )
