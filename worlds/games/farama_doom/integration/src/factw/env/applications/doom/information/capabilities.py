"""Inspect existing information grants without granting or capturing any data."""

from .evaluation_view import OBJECTIVE_CRITERIA, evaluation_view
from .player_observation import player_observation
from .privileged_state import reference_view
from .profiles import scenario_profiles
from .recording_view import RecordingView


def _implementation(value):
    return f"{value.__module__}:{value.__qualname__}"


def describe_capabilities(scenario):
    profiles = scenario_profiles(scenario)["profiles"]
    policy = profiles["reference-assisted"]["policy"]
    return {
        "player_observation": {
            "projection": _implementation(player_observation),
            "fields": profiles["player-observation"]["player_fields"],
            "view_available": profiles["player-observation"]["view_available"],
            "supplied_agent_available": profiles["player-observation"]["agent_available"],
            "native_exit_from_rgb": "unavailable",
        },
        "privileged_state": {
            "projection": _implementation(reference_view),
            "provider_access_policy": policy["access_policy_id"],
            "episode_fields": [*policy["provider_reference_fields"][:1], "active"],
            "game_variables": policy["provider_reference_fields"][1:],
            "label_fields": policy["provider_label_fields"],
            "assistance": policy["assistance"],
        },
        "recording": {
            "projection": _implementation(RecordingView),
            "configuration_fields": ["public_game_variables", "public_labels", "depth"],
            "grants_provider_channels": False,
            "private_inspection": "separate-privileged-output",
        },
        "evaluation": {
            "projection": _implementation(evaluation_view),
            "metadata_fields": [
                "scenario",
                "capture_id",
                "episode_tics",
                "terminated",
                "truncated",
            ],
            "game_variables": list(OBJECTIVE_CRITERIA[scenario]),
            "grants_provider_channels": False,
            "provider_claims_are_evidence": False,
        },
    }
