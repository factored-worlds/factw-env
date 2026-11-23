"""Use Doom scenarios directly, without an agent or State Language SDK."""

import argparse
import json
from contextlib import ExitStack
from pathlib import Path

from factw.env.core.recording.jsonio import json_value

from . import native
from .assets import SCENARIOS, scenario_configuration, scenario_directory


def selection(parser, *, default_start=0):
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--scenario", choices=tuple(SCENARIOS))
    source.add_argument("--native-preset", choices=tuple(native.BUNDLED))
    parser.add_argument("--scenario-dir", type=Path)
    parser.add_argument("--start", type=int, default=default_start)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="operation", required=True)
    commands.add_parser("scenarios")
    play = commands.add_parser("play")
    selection(play, default_start=None)
    play.add_argument("--worker-python", required=True, type=Path)
    play.add_argument("--output", required=True, type=Path)
    play.add_argument("--map", default="MAP01")
    play.add_argument("--skill", type=int, choices=range(1, 6), default=3)
    play.add_argument("--seed", type=int, help="Play the generated navigation map for this seed")
    play.add_argument("--episodes", type=int, default=1)
    play.add_argument("--max-tics", type=int)
    play.add_argument("--resolution", default="RES_800X600")
    play.add_argument("--iwad", type=Path)
    play.add_argument("--silent", action="store_true")
    play.add_argument("--headless", action="store_true")
    replay = commands.add_parser("replay")
    replay.add_argument("run", type=Path)
    replay.add_argument("--worker-python", required=True, type=Path)
    replay.add_argument("--output", required=True, type=Path)
    replay.add_argument("--episode", type=int, default=0)
    replay.add_argument("--silent", action="store_true")
    replay.add_argument("--headless", action="store_true")
    collect = commands.add_parser("collect")
    selection(collect)
    collect.add_argument("--worker-python", required=True, type=Path)
    collect.add_argument("--output", required=True, type=Path)
    collect.add_argument("--actions", required=True, type=Path)
    collect.add_argument("--seed", type=int, default=0)
    collect.add_argument("--max-steps", type=int, default=1000)
    collect.add_argument("--references", action="store_true")
    collect.add_argument("--evaluate", action="store_true")
    args = parser.parse_args()
    if args.operation == "scenarios":
        report = native.scenarios()
    elif args.operation == "play":
        report = native.play(
            args.output,
            args.worker_python,
            scenario=args.scenario,
            native_preset=args.native_preset,
            scenario_dir=args.scenario_dir,
            start=args.start,
            doom_map=args.map,
            skill=args.skill,
            seed=args.seed,
            episodes=args.episodes,
            max_tics=args.max_tics,
            resolution=args.resolution,
            iwad=args.iwad,
            sound=not args.silent,
            visible=not args.headless,
        )
    elif args.operation == "replay":
        report = native.replay(
            args.run,
            args.output,
            args.worker_python,
            episode=args.episode,
            sound=not args.silent,
            visible=not args.headless,
        )
    else:
        from factw.env.external.collect import collect

        with ExitStack() as resources:
            if args.scenario in native.MISSIONS:
                directory = args.scenario_dir
                if directory is None:
                    directory = resources.enter_context(scenario_directory(args.scenario))
                config, _ = scenario_configuration(directory, start=args.start)
            else:
                if args.start != 0 or args.scenario_dir is not None:
                    raise ValueError("--start and --scenario-dir select authored mission fixtures")
                config = {"scenario": args.native_preset or "basic"}
            actions = json_value(args.actions.read_text(encoding="utf-8"))
            if type(actions) is not list or any(
                type(value) is not dict or not value for value in actions
            ):
                raise ValueError("Actions must contain a list of nonempty command objects")
            runtime = args.worker_python.absolute()
            runtime.stat()
            path = collect(
                args.output,
                (str(runtime), "-m", "factw.env.workers.farama"),
                "vizdoom",
                config,
                actions,
                seed=args.seed,
                max_steps=args.max_steps,
                references=args.references,
                evaluate=args.evaluate,
                task_id=args.scenario,
            )
            identity = {
                "schema": "factored-worlds-doom-selection/1",
                "case_id": "games.doom",
                "scenario_id": args.scenario,
                "native_preset": args.native_preset
                or ("basic" if args.scenario not in native.MISSIONS else None),
                "start": args.start,
            }
            (args.output / "selection.json").write_text(json.dumps(identity, indent=2) + "\n")
            report = {"episode": str(path), "selection": identity}
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
