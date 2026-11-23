"""Bind suite names to the shared single- and multi-agent adapters lazily."""

from functools import partial


def single(suite, config):
    from .single_agent import GymnasiumBackend

    return GymnasiumBackend(config, suite=suite)


def multi(suite, config):
    from .multiagent import Backend

    return Backend(config, suite=suite)


gymnasium = partial(single, "gymnasium")
gymnasium_robotics = partial(single, "gymnasium-robotics")
metaworld = partial(single, "metaworld")
highway = partial(single, "highway")
miniwob = partial(single, "miniwob")
ale = partial(single, "ale")
stable_retro = partial(single, "stable-retro")
shimmy = partial(single, "shimmy")
pettingzoo = partial(multi, "pettingzoo")
mpe2 = partial(multi, "mpe2")
magent2 = partial(multi, "magent2")
momaland = partial(multi, "momaland")
