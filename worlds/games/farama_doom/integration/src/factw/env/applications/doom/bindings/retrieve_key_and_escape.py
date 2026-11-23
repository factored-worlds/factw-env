"""Explicit navigation provider wiring and application output validation."""

from ..contracts import navigation as schema
from ..contracts.validation import validate_output as validate_payload
from ..information.access_policy import InformationBoundary
from ..information.privileged_state import NAVIGATION
from ..providers.subsymbolic.control import navigation_native_pose as control
from ..providers.subsymbolic.estimation import navigation_telemetry as estimation
from ..providers.subsymbolic.execution import SkillDispatcher as Dispatcher
from ..providers.subsymbolic.refinement import navigation_known_topology as refinement
from ..providers.symbolic.grounding import navigation_telemetry as grounding
from ..providers.symbolic.planning import navigation as planning
from ..scenarios.retrieve_key_and_escape import skills
from .registry import register_providers


class SkillDispatcher(Dispatcher):
    def __init__(self):
        super().__init__(skills)


def register(registry, *, boundary, planner=None):
    if not isinstance(boundary, InformationBoundary) or boundary.scenario != NAVIGATION:
        raise ValueError("Navigation providers require their scenario information boundary")
    dispatcher = SkillDispatcher()
    register_providers(
        registry,
        [
            (
                "doom.telemetry",
                "subsymbolic.estimate",
                ("estimate", "estimate"),
                estimation.estimate,
            ),
            (
                "doom.ground",
                "symbolic.ground",
                ("updates", "knowledge_updates"),
                lambda estimate: grounding.ground(estimate),
            ),
            (
                "doom.plan" if planner is None else planner.provider_id,
                "symbolic.plan",
                ("plan", "plan"),
                planning.plan if planner is None else planner.function,
            ),
            ("doom.refine", "subsymbolic.refine_skill", ("target", "target"), refinement.refine),
            (
                "doom.execute",
                "subsymbolic.execute_skill",
                ("outcome", "outcome"),
                dispatcher.execute,
            ),
            ("doom.control", "subsymbolic.control_step", ("command", "command"), control.control),
        ],
        boundary=boundary,
    )
    return dispatcher


def validate_output(identifier, value):
    validate_payload(
        identifier,
        value,
        prefix="doom",
        schema=schema,
        policy=skills,
        ground=grounding.ground,
        buttons={"MOVE_FORWARD", "TURN_LEFT", "TURN_RIGHT", "USE"},
    )
