"""Run the declared retrieve key and escape task."""

from contextlib import ExitStack
from pathlib import Path
from secrets import randbits
from tempfile import TemporaryDirectory

from factw.env.worlds.doom.assets import scenario_directory
from factw.env.worlds.doom.navigation_map import build_navigation_map

from ...recording.mission import record_mission

SCENARIO_ID = "games.doom/retrieve-key-and-escape"


def run(
    output,
    worker_command,
    *,
    seed=None,
    start=None,
    max_steps=500,
    max_skill_steps=80,
    visible=False,
    button_window=False,
    scenario_dir=None,
    presentation=None,
    planner=None,
    information_profile="reference-assisted",
    startup_iwad=None,
    real_time=False,
):
    from . import NavigationSession

    if seed is None:
        seed = randbits(31) if start is None else 0
    if type(seed) is not int or not 0 <= seed < 2**31:
        raise ValueError("seed must be an integer from 0 to 2147483647")
    generated = scenario_dir is None and start is None
    with ExitStack() as assets:
        directory = scenario_dir
        if directory is None:
            directory = assets.enter_context(scenario_directory(SCENARIO_ID))
            if generated:
                staged = Path(assets.enter_context(TemporaryDirectory())) / "scenario_assets"
                build_navigation_map(directory, staged, seed)
                directory = staged
                start = 0
        return record_mission(
            output,
            worker_command,
            seed=seed,
            start=start,
            max_steps=max_steps,
            max_skill_steps=max_skill_steps,
            visible=visible,
            button_window=button_window,
            scenario_dir=directory,
            archive_map=generated,
            session_type=NavigationSession,
            mission=SCENARIO_ID,
            presentation=presentation,
            planner=planner,
            information_profile=information_profile,
            startup_iwad=startup_iwad,
            real_time=real_time,
        )
