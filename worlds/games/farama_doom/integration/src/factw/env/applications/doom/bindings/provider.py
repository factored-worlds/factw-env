"""Adapt Python computations to native provider records."""

from factw.env.core.state_language.records import decode, encode

from ..information.access_policy import InformationBoundary


def unpack(value):
    return decode(value) if isinstance(value, dict) and set(value) == {"json"} else value


class Provider:
    def __init__(self, output, function, *, contract, boundary):
        if not isinstance(boundary, InformationBoundary):
            raise ValueError("Doom providers require an information boundary")
        self.output, self.function = output, function
        self.contract, self.boundary = contract, boundary

    def invoke(self, call):
        values = {name: unpack(record["value"]) for name, record in call["inputs"].items()}
        values = self.boundary.provider_inputs(self.contract, values)
        result = self.function(**values)
        port, output_schema = self.output
        return {
            port: {
                "schema": output_schema,
                "value": encode(result),
                "basis": call["basis"],
                "sequence": max(record["sequence"] for record in call["inputs"].values()),
            }
        }

    def cancel(self, invocation):
        return True

    def close(self):
        pass
