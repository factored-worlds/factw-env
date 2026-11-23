"""Run the declared activate reactor and extract task."""

from contextlib import nullcontext

from factw.env.worlds.doom.assets import scenario_directory

from ...recording.mission import record_mission

SCENARIO_ID = "games.doom/activate-reactor-and-extract"


def run(
    output,
    worker_command,
    *,
    seed=0,
    start=0,
    max_steps=2000,
    max_skill_steps=240,
    visible=False,
    button_window=False,
    scenario_dir=None,
    presentation=None,
    planner=None,
    information_profile="reference-assisted",
    startup_iwad=None,
    buffered_media=False,
    paced=False,
    real_time=False,
):
    from ...missions.combat import CombatSession

    assets = scenario_directory(SCENARIO_ID) if scenario_dir is None else nullcontext(scenario_dir)
    with assets as directory:
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
            session_type=CombatSession,
            mission=SCENARIO_ID,
            presentation=presentation,
            planner=planner,
            information_profile=information_profile,
            startup_iwad=startup_iwad,
            buffered_media=buffered_media,
            paced=paced,
            real_time=real_time,
        )
