from ...bindings import retrieve_key_and_escape as providers
from ...contracts import navigation as schema
from ...runtime.documents import load_definition
from . import skills as policy

config_name = "key_door_exit.cfg"
scenario = "games.doom/retrieve-key-and-escape"


def definition(scope=None, *, planner=None):
    return load_definition(scenario, scope=scope, planner=planner)


__all__ = ["policy", "providers", "schema", "definition", "config_name"]
