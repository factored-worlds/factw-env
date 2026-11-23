"""Switch a symbolic planner using real SMSL capture and invocation, without Doom."""

import json

import smsl
from factw.env.applications.doom.bindings import activate_reactor_and_extract as combat
from factw.env.applications.doom.bindings.registry import register_providers
from factw.env.applications.doom.information.access_policy import InformationBoundary
from factw.env.applications.doom.missions.combat.skills import POSTCONDITIONS
from factw.env.applications.doom.providers.symbolic.planning.combat import (
    plan as priority_plan,
)
from factw.env.core.state_language.records import decode
from factw.env.worlds.doom.assets import document_sources

SCENARIO_ID = "games.doom/activate-reactor-and-extract"


def resupply_first(knowledge, goal):
    if "resupply" in knowledge["availableActions"]:
        return {
            "status": "ready",
            "action": "resupply",
            "postcondition": POSTCONDITIONS["resupply"],
        }
    return priority_plan(knowledge, goal)


def load_application(provider):
    documents = document_sources(SCENARIO_ID)
    sources = {
        name: smsl.Source(documents[name]) for name in ("domain.smsl", "task.smsl", "system.smsl")
    }
    system = smsl.SystemDefinition.loads(documents["system.smsl"]).to_dict()
    planner = next(component for component in system["components"] if component["id"] == "planner")
    planner["blocks"][0]["provider"] = provider
    sources["system.smsl"] = smsl.Source(json.dumps(system), "json")
    return smsl.ApplicationDefinition.loads(documents["application.smsl"], sources=sources)


def invoke_planner(provider, implementation):
    application = load_application(provider)
    world = smsl.create_application_world(application)
    context = world.snapshot("scene").context
    # A declared fixture supplies observations; this example does not infer them.
    for tick, fact in enumerate(
        ("active", "alive", "health_low", "health_available", "ammo_low", "ammo_available"), 1
    ):
        world.advance(
            "scene", smsl.Event(f"observed_{fact}", tick, context, payload={"value": True})
        )

    bindings = smsl.ApplicationBindings(application, world)
    captured = bindings.capture("planner.plan", sequence=1)
    registry = smsl.ProviderRegistry()
    boundary = InformationBoundary(SCENARIO_ID)
    combat.register(registry, boundary=boundary)
    register_providers(
        registry,
        [(provider, "symbolic.plan", ("plan", "plan"), implementation)],
        boundary=boundary,
    )

    def validate(outputs, call):
        combat.validate_output("doom.combat.plan.v1", decode(outputs["plan"]["value"]))

    bridge = smsl.WorldBridge(world, "scene")
    with application.system_definition().session(registry, captured["basis"]) as session:
        outputs = session.invoke(
            "planner.plan",
            "choose-skill",
            inputs=captured["inputs"],
            current_basis=bridge.basis,
            validate_outputs=validate,
        )
    return {
        "scenario": SCENARIO_ID,
        "information_profile": "reference-assisted",
        "input_condition": "declared-fact-fixture",
        "native_simulation": False,
        "provider": registry.describe(provider),
        "contract": "symbolic.plan",
        "available_actions": captured["inputs"]["knowledge"]["value"]["availableActions"],
        "plan": decode(outputs["plan"]["value"]),
    }


def compare():
    return [
        invoke_planner("demo.priority", priority_plan),
        invoke_planner("demo.resupply_first", resupply_first),
    ]


if __name__ == "__main__":
    print(json.dumps(compare(), indent=2))
