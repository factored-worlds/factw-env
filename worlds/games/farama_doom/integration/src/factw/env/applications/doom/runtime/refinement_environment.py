"""Project each actual native capture once without granting native metadata."""

from uuid import uuid4

from ..information.player_observation import player_observation


class PlayerEnvironment:
    def __init__(self, environment, initial_observation):
        self._environment = environment
        self._capture = None
        self._record(initial_observation)

    @property
    def metadata(self):
        return self._environment.metadata

    @property
    def terminated(self):
        return self._environment.terminated

    @property
    def truncated(self):
        return self._environment.truncated

    def _record(self, observation):
        self._capture = (
            None
            if observation.rgb is None
            else player_observation(observation, capture_id=uuid4().hex)
        )

    def capture(self):
        observation, self._capture = self._capture, None
        return observation

    def step(self, command):
        self._capture = None
        result = self._environment.step(command)
        self._record(result.observation)
        return result
