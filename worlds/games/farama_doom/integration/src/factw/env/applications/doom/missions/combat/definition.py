from ...bindings import activate_reactor_and_extract as providers
from ...contracts import combat as schema
from ...runtime.documents import load_definition
from . import skills as policy

config_name = "combat_mission.cfg"
scenario = "games.doom/activate-reactor-and-extract"


def definition(scope=None, *, planner=None):
    return load_definition(scenario, scope=scope, planner=planner)


__all__ = ["policy", "providers", "schema", "definition", "config_name"]
