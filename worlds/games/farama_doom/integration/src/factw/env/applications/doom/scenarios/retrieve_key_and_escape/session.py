"""Navigation specialization of the shared observed mission loop."""

from ...runtime.mission_session import Decision, MissionSession, NavigationStep
from . import definition as mission


class NavigationSession(MissionSession):
    def __init__(
        self,
        environment,
        scene_spec=None,
        *,
        max_skill_steps=80,
        stuck_steps=12,
        planner=None,
        information_profile="reference-assisted",
    ):
        super().__init__(
            environment,
            mission,
            scene_spec,
            max_skill_steps=max_skill_steps,
            stuck_steps=stuck_steps,
            planner=planner,
            information_profile=information_profile,
        )


__all__ = ["Decision", "NavigationSession", "NavigationStep"]
