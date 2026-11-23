import json
import os
import selectors
import subprocess
import time
from contextlib import contextmanager

from factw.env.core.recording.jsonio import json_object

MAX_MESSAGE_BYTES = 2 * 1024 * 1024


class Transport:
    def __init__(
        self,
        process: subprocess.Popen,
        timeout: float,
        *,
        protocol: str,
        max_message_bytes: int = MAX_MESSAGE_BYTES,
    ):
        self.process = process
        self.timeout = timeout
        self.protocol = protocol
        self.max_message_bytes = max_message_bytes
        self.sequence = 0
        self.buffer = bytearray()

    def request(self, operation: str, payload: dict) -> dict:
        self.sequence += 1
        message = {
            "protocol": self.protocol,
            "id": self.sequence,
            "operation": operation,
            "payload": payload,
        }
        encoded = (json.dumps(message, allow_nan=False) + "\n").encode()
        if len(encoded) > self.max_message_bytes:
            raise ValueError("Simulator worker request exceeds the message limit")
        deadline = time.monotonic() + self.timeout
        self._write(encoded, deadline)
        reply = json_object(self._line(deadline).decode("utf-8"))
        if set(reply) != {"protocol", "id", "result"} or (
            reply["protocol"] != self.protocol
            or type(reply["id"]) is not int
            or reply["id"] != self.sequence
            or type(reply["result"]) is not dict
        ):
            raise ValueError("Simulator worker returned a mismatched response")
        return reply["result"]

    def _write(self, encoded: bytes, deadline: float) -> None:
        descriptor = self.process.stdin.fileno()
        blocking = os.get_blocking(descriptor)
        os.set_blocking(descriptor, False)
        try:
            with selectors.DefaultSelector() as selector:
                selector.register(self.process.stdin, selectors.EVENT_WRITE)
                remaining_bytes = memoryview(encoded)
                while remaining_bytes:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0 or not selector.select(remaining):
                        raise TimeoutError(
                            "Simulator worker request timed out; inspect its stderr log"
                        )
                    written = os.write(descriptor, remaining_bytes)
                    remaining_bytes = remaining_bytes[written:]
        finally:
            os.set_blocking(descriptor, blocking)

    def _line(self, deadline: float) -> bytes:
        with selectors.DefaultSelector() as selector:
            selector.register(self.process.stdout, selectors.EVENT_READ)
            while b"\n" not in self.buffer:
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not selector.select(remaining):
                    raise TimeoutError(
                        "Simulator worker response timed out; inspect its stderr log"
                    )
                data = os.read(self.process.stdout.fileno(), 65536)
                if not data:
                    raise RuntimeError(
                        "Simulator worker exited without a response; inspect its stderr log"
                    )
                self.buffer.extend(data)
                if len(self.buffer) > self.max_message_bytes:
                    raise ValueError("Simulator worker exceeded the message limit")
        line, _, rest = self.buffer.partition(b"\n")
        self.buffer = bytearray(rest)
        return bytes(line)


@contextmanager
def worker(
    command: tuple[str, ...],
    *,
    timeout: float,
    stderr,
    protocol: str,
    max_message_bytes: int = MAX_MESSAGE_BYTES,
):
    if not command or any(type(arg) is not str or not arg for arg in command):
        raise ValueError("Simulator worker command must contain nonempty argument strings")
    if type(timeout) not in (int, float) or not 0 < timeout < float("inf"):
        raise ValueError("Simulator worker timeout must be positive and finite")
    if type(protocol) is not str or not protocol:
        raise ValueError("Simulator worker protocol must be a nonempty string")
    if type(max_message_bytes) is not int or max_message_bytes < 1:
        raise ValueError("Worker message limit must be a positive integer")
    process = subprocess.Popen(
        command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=stderr, bufsize=0
    )
    forced_shutdown = False
    try:
        yield Transport(process, timeout, protocol=protocol, max_message_bytes=max_message_bytes)
    finally:
        process.stdin.close()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            forced_shutdown = True
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        process.stdout.close()
    if not forced_shutdown and process.returncode != 0:
        raise subprocess.CalledProcessError(process.returncode, command)
