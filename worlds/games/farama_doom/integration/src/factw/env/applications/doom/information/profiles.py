"""Scenario information conditions and availability of supplied agent compositions."""

from .privileged_state import BASIC, COMBAT, LABEL_FIELDS, NAVIGATION, REFERENCE_VARIABLES

PROFILE_NAMES = ("reference-assisted", "player-observation")
_CONDITION_IDS = {
    BASIC: (
        "games.doom/basic-killcount-and-lateral-position",
        "games.doom/workflow-doom-basic-basic-killcount-and-lateral-position-access",
    ),
    NAVIGATION: (
        "games.doom/navigation-telemetry-and-known-topology",
        "games.doom/workflow-doom-key-door-exit-navigation-telemetry-and-known-topology-access",
    ),
    COMBAT: (
        "games.doom/mission-telemetry-and-known-topology",
        "games.doom/workflow-doom-combat-mission-mission-telemetry-and-known-topology-access",
    ),
}


def scenario_profiles(scenario):
    if type(scenario) is not str or scenario not in _CONDITION_IDS:
        raise ValueError("Unknown Doom scenario for information profiles")
    observation_profile, access_policy = _CONDITION_IDS[scenario]
    policy = {
        "schema": "doom.information-policy/1",
        "scenario": scenario,
        "profile": "reference-assisted",
        "observation_profile_id": observation_profile,
        "access_policy_id": access_policy,
        "provider_reference_fields": ["episode_tics", *REFERENCE_VARIABLES[scenario]],
        "provider_label_fields": list(LABEL_FIELDS) if scenario == COMBAT else [],
        "player_fields": ["rgb"],
        "assistance": ["native-telemetry"]
        + (["authored-topology"] if scenario != BASIC else [])
        + (["native-visible-object-labels"] if scenario == COMBAT else []),
        "recording": "full-declared-native-observation-and-private-inspection",
        "evaluator": "independent-native-objective-signals",
        "continuation": "fresh-environment-replay-only",
    }
    return {
        "scenario": scenario,
        "profiles": {
            "reference-assisted": {
                "agent_available": True,
                "view_available": True,
                "policy": policy,
            },
            "player-observation": {
                "agent_available": False,
                "view_available": True,
                "player_fields": ["rgb"],
                "assistance": [],
                "view_requirement": "An available native RGB capture",
                "unavailable_reason": "A player-observation policy is not implemented",
            },
        },
    }


def require_agent_profile(scenario, profile):
    profiles = scenario_profiles(scenario)["profiles"]
    if type(profile) is not str or profile not in profiles:
        raise ValueError("Unknown Doom information profile")
    selected = profiles[profile]
    if not selected["agent_available"]:
        raise ValueError(selected["unavailable_reason"])
    return selected
