import argparse
import json
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from factw.env.worlds.doom.assets import SCENARIOS

from .information.profiles import PROFILE_NAMES, require_agent_profile
from .viewer import inspection, write_viewer


def main():
    parser = argparse.ArgumentParser(
        description="Run and inspect Environment Doom applications with State Language"
    )
    commands = parser.add_subparsers(dest="operation", required=True)
    from .recording.demonstration_cli import add_commands

    add_commands(commands)
    from .host.refinement_cli import add_command

    add_command(commands)
    commands.add_parser("compare-providers", help="Compare two symbolic planners through the SDK")
    profiles = commands.add_parser(
        "profiles", help="Inspect dedicated scenario information profiles and provider compositions"
    )
    profiles.add_argument("--scenario", choices=SCENARIOS)
    run = commands.add_parser("run")
    run.add_argument(
        "--scenario",
        choices=SCENARIOS,
        default="games.doom/activate-reactor-and-extract",
    )
    run.add_argument("--worker-python", type=Path, required=True)
    run.add_argument("--output", type=Path, required=True)
    run.add_argument("--seed", type=int, help="Repeat the generated navigation map and engine seed")
    run.add_argument("--start", type=int, help="Select an explicit authored fixture index")
    run.add_argument("--max-steps", type=int)
    run.add_argument("--max-skill-steps", type=int)
    run.add_argument("--scenario-dir", type=Path)
    run.add_argument("--iwad", type=Path, help="Select the declared native IWAD explicitly")
    run.add_argument(
        "--planner", help="Pure planner replacement as module:factory (authored missions)"
    )
    run.add_argument(
        "--information-profile",
        choices=PROFILE_NAMES,
        default="reference-assisted",
        help="Player pixels are supported; the supplied Doom policy requires reference assistance",
    )
    run.add_argument("--visible", action="store_true")
    run.add_argument(
        "--button-window",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Show applied Doom buttons in a separate window (default: on with --visible)",
    )
    run.add_argument("--sound", action="store_true")
    run.add_argument("--resolution")
    run.add_argument("--skill", type=int, choices=range(1, 6))
    run.add_argument(
        "--buffered-media",
        action="store_true",
        help="Use bounded background recording for Reactor and Extract",
    )
    clock = run.add_mutually_exclusive_group()
    clock.add_argument(
        "--real-time",
        action="store_true",
        help="Pace an authored mission to native elapsed time without opening an engine window",
    )
    clock.add_argument(
        "--paced",
        action="store_true",
        help="Run Reactor and Extract on a separate 35 Hz bridge clock",
    )
    for name in ("inspect", "view"):
        commands.add_parser(name).add_argument("run", type=Path)
    args = parser.parse_args()
    if args.operation == "demonstration":
        from .recording.demonstration_cli import handle

        report = handle(args)
    elif args.operation == "discover":
        from .host.refinement_cli import handle

        report = handle(args)
    elif args.operation == "composition":
        from .host.refinement_cli import inspect_composition

        report = inspect_composition(args)
    elif args.operation == "inspect":
        report = inspection(args.run)
    elif args.operation == "view":
        report = {"viewer": str(write_viewer(args.run))}
    elif args.operation == "compare-providers":
        from .comparison import compare

        report = compare()
    elif args.operation == "profiles":
        from .host.profile_inspection import describe_profiles

        scenarios = SCENARIOS if args.scenario is None else (args.scenario,)
        report = {"scenarios": [describe_profiles(scenario) for scenario in scenarios]}
    else:
        from .host.planner import load_planner

        require_agent_profile(args.scenario, args.information_profile)
        if args.scenario != "games.doom/retrieve-key-and-escape":
            if args.seed is None:
                args.seed = 0
            if args.start is None:
                args.start = 0
        if (
            args.buffered_media or args.paced
        ) and args.scenario != "games.doom/activate-reactor-and-extract":
            parser.error("Buffered and paced execution select Reactor and Extract")
        recording_options = {"buffered_media": True} if args.buffered_media else {}
        if args.paced:
            try:
                runtime_version = version("smsl-runtime")
            except PackageNotFoundError:
                runtime_version = None
            if runtime_version != "0.2.0rc9":
                parser.error("Install factored-worlds-doom-application[paced] to enable paced Doom")
            recording_options["paced"] = True
        planner = None if args.planner is None else load_planner(args.planner, args.scenario)
        runtime = args.worker_python.absolute()
        runtime.stat()
        worker = (str(runtime), "-m", "factw.env.workers.farama")
        presentation = {}
        if args.sound:
            presentation["sound_enabled"] = True
        if args.resolution is not None:
            presentation["resolution"] = args.resolution
        if args.skill is not None:
            presentation["doom_skill"] = args.skill
        button_window = args.visible if args.button_window is None else args.button_window
        if args.scenario == "games.doom/eliminate-single-target":
            from .scenarios.eliminate_single_target.run import run

            if args.real_time:
                parser.error("--real-time selects an authored mission")
            if args.iwad is not None:
                parser.error("--iwad selects an authored mission")
            if args.start != 0:
                parser.error(
                    "--start selects authored missions; this scenario uses its native seed"
                )
            if args.scenario_dir is not None or args.max_skill_steps is not None:
                parser.error("--scenario-dir and --max-skill-steps select authored missions")
            report = run(
                args.output,
                worker,
                seed=args.seed,
                max_steps=150 if args.max_steps is None else args.max_steps,
                visible=args.visible,
                button_window=button_window,
                presentation=presentation,
                information_profile=args.information_profile,
            )
            write_viewer(args.output)
        else:
            if args.scenario == "games.doom/activate-reactor-and-extract":
                from .scenarios.activate_reactor_and_extract.run import run

                default_steps, default_skill_steps = 2000, 240
            else:
                from .scenarios.retrieve_key_and_escape.run import run

                default_steps, default_skill_steps = 500, 80
            if args.visible:
                presentation["render_all_frames"] = True
            report = run(
                args.output,
                worker,
                seed=args.seed,
                start=args.start,
                max_steps=default_steps if args.max_steps is None else args.max_steps,
                max_skill_steps=default_skill_steps
                if args.max_skill_steps is None
                else args.max_skill_steps,
                visible=args.visible,
                button_window=button_window,
                scenario_dir=args.scenario_dir,
                presentation=presentation,
                planner=planner,
                information_profile=args.information_profile,
                startup_iwad=args.iwad,
                real_time=args.real_time,
                **recording_options,
            )
    print(json.dumps(report, indent=2))
