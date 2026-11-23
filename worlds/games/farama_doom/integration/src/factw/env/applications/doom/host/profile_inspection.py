"""Inspect supplied information conditions and their actual provider compositions."""

from inspect import signature

import smsl
from factw.env.worlds.doom.assets import document_sources, scenario_identity

from ..information.access_policy import InformationBoundary
from ..information.capabilities import describe_capabilities
from ..information.privileged_state import BASIC, COMBAT, NAVIGATION
from ..information.profiles import require_agent_profile, scenario_profiles
from ..providers.symbolic.single_target_native_pose import SweepPolicy


def describe_profiles(scenario, *, planner=None):
    description = scenario_profiles(scenario)
    description.update(scenario_identity(scenario))
    description["information_capabilities"] = describe_capabilities(scenario)
    documents = sorted(document_sources(scenario))
    if scenario == BASIC:
        if planner is not None:
            raise ValueError("Doom Basic has no replaceable symbolic planner block")
        policy = SweepPolicy.choose
        composition = {
            "kind": "host-policy-with-task-monitor",
            "smsl": documents,
            "policy": {
                "kind": "symbolic",
                "implementation": f"{policy.__module__}:{policy.__qualname__}",
                "inputs": list(signature(SweepPolicy().choose).parameters),
            },
        }
    else:
        from ..missions.combat import definition as combat
        from ..scenarios.retrieve_key_and_escape import definition as navigation

        mission = {NAVIGATION: navigation, COMBAT: combat}[scenario]
        application = mission.definition(planner=planner)
        system = application.system_definition().to_dict()
        registry = smsl.ProviderRegistry()
        mission.providers.register(
            registry, boundary=InformationBoundary(scenario), planner=planner
        )
        composition = {
            "kind": "state-language-application",
            "smsl": documents,
            "system": system["id"],
            "blocks": [
                {
                    "id": block["id"],
                    "role": block["role"],
                    "contract": block["contract"],
                    "binding": block["binding"],
                    "provider": registry.describe(block["provider"]),
                }
                for block in application.inspect()["blocks"]
            ],
            "connections": system["connections"],
        }
    description["profiles"]["reference-assisted"]["composition"] = composition
    return description


def selected_profile(scenario, profile, *, planner=None):
    require_agent_profile(scenario, profile)
    description = describe_profiles(scenario, planner=planner)
    return {
        "scenario_id": scenario,
        "scenario_revision": description["scenario_revision"],
        "profile": profile,
        **description["profiles"][profile],
    }
