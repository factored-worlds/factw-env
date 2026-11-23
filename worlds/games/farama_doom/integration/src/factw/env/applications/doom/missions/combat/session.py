"""Interruptible combat and objective planning over observed native evidence."""

from factw.env.worlds.doom.assets import document_bytes

from ...providers.symbolic.grounding.fireball_facts import FireballFacts
from ...runtime.mission_session import MissionSession
from . import definition as mission


class CombatSession(MissionSession):
    def __init__(
        self,
        environment,
        scene_spec=None,
        *,
        max_skill_steps=240,
        stuck_steps=12,
        planner=None,
        information_profile="reference-assisted",
        apply_command=None,
    ):
        config = environment.metadata.get("configuration", {})
        if config.get("frame_skip") != 1 or config.get("public_labels") is not True:
            raise ValueError("CombatSession requires one-tic control and declared visible labels")
        super().__init__(
            environment,
            mission,
            scene_spec,
            max_skill_steps=max_skill_steps,
            stuck_steps=stuck_steps,
            planner=planner,
            information_profile=information_profile,
            apply_command=apply_command,
        )

    def _clear(self):
        super()._clear()
        self._fireball_facts = None

    def _observe(self, observation):
        super()._observe(observation)
        if self._fireball_facts is None:
            context = self._world.snapshot("scene").context
            self._fireball_facts = FireballFacts(
                self._world,
                document_bytes(mission.scenario)["fireball.smsl"],
                scope=context.scope,
                clock=context.clock,
            )
        self._fireball_facts.observe(self.estimate, tick=self._event_time)

    def inspect(self, *, history=True):
        state = super().inspect(history=history)
        return {**state, "fireballs": self._fireball_facts.facts()}


__all__ = ["CombatSession"]
