"""Optional State Language admission and observed episode tracking."""

from importlib.resources import files
from uuid import uuid4

import smsl
from factw.env.core.state_language.records import decode, describe, encode


class StepProvider:
    def __init__(self, environment):
        self.environment = environment
        self.result = None

    def invoke(self, call):
        self.result = None
        command = decode(call["inputs"]["command"]["value"])
        self.result = self.environment.step(command)
        return {
            "transition": {
                "schema": "engines.transition/1",
                "value": encode(describe(self.result)),
                "basis": call["basis"],
                "sequence": call["basis"]["tick"] + 1,
            }
        }

    def cancel(self, invocation):
        raise RuntimeError("Synchronous simulator steps cannot be cancelled while in flight")

    def close(self):
        self.result = None


class StateLanguageSession:
    """Wrap an already connected environment; its caller retains worker ownership."""

    def __init__(self, environment):
        self.environment = environment
        documents = files(__package__).joinpath("smsl")
        self.definition = smsl.SystemDefinition.loads(documents.joinpath("system.smsl").read_text())
        self.machine = smsl.loads(documents.joinpath("episode.smsl").read_text())
        self.session = None
        self.world = None
        self._basis = None
        self._active = False

    @property
    def basis(self):
        if self._basis is None:
            raise RuntimeError("Reset before requesting a basis")
        return dict(self._basis)

    def reset(self, *, seed=0):
        self.close()
        self.world = None
        self._basis = None
        observation = self.environment.reset(seed=seed)
        self.world = smsl.World()
        self.context = smsl.Context("engines", "episode", "steps")
        self.world.spawn("episode", self.machine, self.context)
        self._event_time = 0
        self._basis = {"revision": str(uuid4()), "tick": 0}
        self.provider = StepProvider(self.environment)
        registry = smsl.ProviderRegistry().register(
            name="engines.step",
            contracts=["engines.step.v1"],
            factory=lambda config: self.provider,
            metadata={"title": "Observed environment transition", "persistence": "external"},
        )
        self.session = self.definition.session(registry, self.basis)
        self._active = not (self.environment.terminated or self.environment.truncated)
        if not self._active:
            self._observe(self.environment.terminated, self.environment.truncated, "reset_boundary")
        return observation

    def _observe(self, terminated, truncated, outcome):
        self._event_time += 1
        self.world.advance(
            "episode",
            smsl.Event(
                "observed",
                self._event_time,
                self.context,
                payload={"terminated": terminated, "truncated": truncated, "outcome": outcome},
            ),
        )

    def step(self, command, *, basis):
        if not self._active or self.session is None:
            raise RuntimeError("Reset before stepping an inactive State Language session")
        if basis != self.basis:
            raise ValueError("Command basis is stale")
        payload = encode(command)
        self._active = False
        self.session.invoke(
            "environment.step",
            f"step-{self._basis['tick']}",
            inputs={
                "command": {
                    "schema": "engines.command/1",
                    "value": payload,
                    "basis": self.basis,
                    "sequence": self._basis["tick"] + 1,
                }
            },
            allow_effects=True,
            current_basis=lambda: self.basis,
        )
        result = self.provider.result
        self._observe(result.terminated, result.truncated, result.outcome)
        self._basis = {**self._basis, "tick": self._basis["tick"] + 1}
        self.session.advance(self.basis)
        self._active = not (result.terminated or result.truncated)
        return result

    def inspect(self):
        if self.session is None:
            raise RuntimeError("Reset before inspecting the session")
        return {
            "basis": self.basis,
            "facts": {
                key: None if value is smsl.UNKNOWN else value
                for key, value in self.world.snapshot("episode").facts("Episode").items()
            },
            "providers": self.session.inspect(),
            "continuation": "The symbolic archive does not restore the upstream simulator.",
        }

    def close(self):
        self._active = False
        if self.session is not None:
            self.session.close()
            self.session = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
