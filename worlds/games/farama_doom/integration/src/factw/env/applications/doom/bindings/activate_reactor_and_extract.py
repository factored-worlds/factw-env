"""Explicit combat provider wiring and application output validation."""

from ..contracts import combat as schema
from ..contracts.validation import validate_output as validate_payload
from ..information.access_policy import InformationBoundary
from ..information.privileged_state import COMBAT
from ..missions.combat import skills
from ..providers.subsymbolic.control import combat_native_pose_and_labels as control
from ..providers.subsymbolic.estimation import combat_telemetry_and_labels as estimation
from ..providers.subsymbolic.execution import SkillDispatcher as Dispatcher
from ..providers.subsymbolic.refinement import combat_known_topology as refinement
from ..providers.symbolic.grounding import combat_telemetry_and_labels as grounding
from ..providers.symbolic.planning import combat as planning
from .registry import register_providers


class SkillDispatcher(Dispatcher):
    def __init__(self):
        super().__init__(skills)


def register(registry, *, boundary, planner=None):
    if not isinstance(boundary, InformationBoundary) or boundary.scenario != COMBAT:
        raise ValueError("Combat providers require their scenario information boundary")
    dispatcher = SkillDispatcher()
    register_providers(
        registry,
        [
            (
                "doom.combat.telemetry",
                "subsymbolic.estimate",
                ("estimate", "estimate"),
                estimation.estimate,
            ),
            (
                "doom.combat.ground",
                "symbolic.ground",
                ("updates", "knowledge_updates"),
                grounding.make_grounder(),
            ),
            (
                "doom.combat.plan" if planner is None else planner.provider_id,
                "symbolic.plan",
                ("plan", "plan"),
                planning.plan if planner is None else planner.function,
            ),
            (
                "doom.combat.refine",
                "subsymbolic.refine_skill",
                ("target", "target"),
                refinement.refine,
            ),
            (
                "doom.combat.execute",
                "subsymbolic.execute_skill",
                ("outcome", "outcome"),
                dispatcher.execute,
            ),
            (
                "doom.combat.control",
                "subsymbolic.control_step",
                ("command", "command"),
                control.control,
            ),
        ],
        boundary=boundary,
        private_contracts=("symbolic.ground",),
    )
    return dispatcher


def validate_output(identifier, value):
    validate_payload(
        identifier,
        value,
        prefix="doom.combat",
        schema=schema,
        policy=skills,
        ground=grounding.ground,
        buttons={
            "MOVE_FORWARD",
            "MOVE_LEFT",
            "MOVE_RIGHT",
            "TURN_LEFT",
            "TURN_RIGHT",
            "USE",
            "ATTACK",
        },
    )
