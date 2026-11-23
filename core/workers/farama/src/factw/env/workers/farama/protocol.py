import json

from .encoding import json_object, transition
from .registry import build

PROTOCOL = "factored-worlds-benchmarks-v3"
MAX_MESSAGE_BYTES = 32 * 1024 * 1024


def serve(source, destination):
    backend = None
    ended = True
    initialized = False
    sequence = 0
    try:
        while line := source.readline(MAX_MESSAGE_BYTES + 1):
            if len(line.encode("utf-8")) > MAX_MESSAGE_BYTES or not line.endswith("\n"):
                raise ValueError("Worker request exceeds the message limit")
            message = json_object(line)
            sequence += 1
            if (
                set(message) != {"protocol", "id", "operation", "payload"}
                or message["protocol"] != PROTOCOL
                or type(message["id"]) is not int
                or message["id"] != sequence
                or type(message["payload"]) is not dict
            ):
                raise ValueError("Malformed benchmark worker request")
            operation, payload = message["operation"], message["payload"]
            if operation == "initialize":
                if backend is not None or set(payload) != {"backend", "config"}:
                    raise ValueError("Initialize one backend per worker process")
                backend = build(payload["backend"], payload["config"])
                result = backend.metadata()
            elif backend is None:
                raise RuntimeError("Initialize the worker first")
            elif operation == "reset":
                if set(payload) != {"seed"} or type(payload["seed"]) is not int:
                    raise ValueError("Reset requires an integer seed")
                initialized = False
                result = transition(backend.reset(payload["seed"]))
                initialized = True
                ended = result["terminated"] or result["truncated"]
            elif operation == "step":
                if ended or set(payload) != {"command"} or type(payload["command"]) is not dict:
                    raise ValueError("Step requires an active episode and a command object")
                result = transition(backend.step(payload["command"]))
                ended = result["terminated"] or result["truncated"]
            elif operation in ("reference", "evaluate", "close"):
                if payload:
                    raise ValueError(f"{operation} does not accept arguments")
                if operation == "close":
                    closing, backend = backend, None
                    closing.close()
                    result = {}
                else:
                    if not initialized:
                        raise RuntimeError("Reset before inspecting an episode")
                    result = getattr(backend, operation)()
                    if operation == "evaluate":
                        ended = True
            else:
                raise ValueError(f"Unknown worker operation: {operation}")
            if type(result) is not dict:
                raise TypeError("Worker operations must return JSON objects")
            response = (
                json.dumps(
                    {"protocol": PROTOCOL, "id": sequence, "result": result}, allow_nan=False
                )
                + "\n"
            )
            if len(response.encode("utf-8")) > MAX_MESSAGE_BYTES:
                raise ValueError("Worker response exceeds the message limit")
            destination.write(response)
            destination.flush()
            if operation == "close":
                break
    finally:
        if backend is not None:
            backend.close()
