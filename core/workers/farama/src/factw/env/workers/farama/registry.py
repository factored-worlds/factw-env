"""Select one installed backend factory without importing other simulators."""

from importlib.metadata import entry_points

ENTRY_POINT_GROUP = "factored_worlds.farama_backends"


def installed_backends():
    plugins = {}
    for entry in entry_points(group=ENTRY_POINT_GROUP):
        if entry.name in plugins:
            raise ValueError(f"Duplicate Farama backend registration: {entry.name}")
        plugins[entry.name] = entry
    return plugins


def backend_names():
    return tuple(sorted(installed_backends()))


def build(name: str, config: dict):
    if type(config) is not dict:
        raise ValueError("Backend configuration must be a JSON object")
    plugins = installed_backends()
    if name not in plugins:
        raise ValueError(f"Unknown Farama backend: {name}; install its owning worker distribution")
    factory = plugins[name].load()
    if not callable(factory):
        raise TypeError(f"Farama backend entry point must be callable: {name}")
    return factory(config)
