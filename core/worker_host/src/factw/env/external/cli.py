import argparse
import json
from pathlib import Path

from factw.env.core.recording import Episode, public_files
from factw.env.core.recording.jsonio import json_value, read_json
from factw.env.external.catalog import catalog
from factw.env.external.collect import collect
from factw.env.external.env import BACKENDS
from factw.env.external.replay import verify


def add_runtime(parser):
    parser.add_argument("--backend", choices=BACKENDS, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--worker-module", help="Explicit module for --worker-python")
    launch = parser.add_mutually_exclusive_group(required=True)
    launch.add_argument("--worker-python", type=Path)
    launch.add_argument("--worker-command", type=Path, help="JSON argv array, e.g. Pixi run")


def worker_command(args):
    if args.worker_python is not None:
        if args.worker_module is None:
            raise ValueError("Supply --worker-module with --worker-python")
        return (str(args.worker_python.absolute()), "-m", args.worker_module)
    if args.worker_module is not None:
        raise ValueError("--worker-module requires --worker-python")
    command = json_value(args.worker_command.read_text(encoding="utf-8"))
    if (
        type(command) is not list
        or not command
        or any(type(arg) is not str or not arg for arg in command)
    ):
        raise ValueError("Worker command must be a nonempty JSON array of argument strings")
    return command


def main():
    parser = argparse.ArgumentParser(description="Run and record upstream world environments")
    commands = parser.add_subparsers(dest="operation", required=True)
    commands.add_parser("list")
    commands.add_parser("catalog")
    dataset_import = commands.add_parser("import-minari")
    dataset_import.add_argument("source", type=Path)
    dataset_import.add_argument("--output", required=True, type=Path)
    dataset_export = commands.add_parser("export-minari")
    dataset_export.add_argument("episodes", nargs="+", type=Path)
    dataset_export.add_argument("--output", required=True, type=Path)
    run = commands.add_parser("collect")
    add_runtime(run)
    run.add_argument("--actions", type=Path, required=True)
    run.add_argument("--output", type=Path, required=True)
    run.add_argument("--seed", type=int, default=0)
    run.add_argument("--max-steps", type=int, default=1000)
    run.add_argument("--references", action="store_true")
    run.add_argument("--evaluate", action="store_true")
    run.add_argument("--smsl", action="store_true", help="Admit steps through State Language")
    audit = commands.add_parser("audit")
    audit.add_argument("episode", type=Path)
    replay = commands.add_parser("verify")
    add_runtime(replay)
    replay.add_argument("episode", type=Path)
    args = parser.parse_args()
    if args.operation == "list":
        report = {"backends": BACKENDS}
    elif args.operation == "catalog":
        report = catalog()
    elif args.operation == "import-minari":
        from factw.env.external.datasets import import_minari

        report = {"episodes": import_minari(args.source, args.output)}
    elif args.operation == "export-minari":
        from factw.env.external.datasets import export_minari

        report = {"output": export_minari(args.episodes, args.output)}
    elif args.operation == "verify":
        report = verify(
            args.episode,
            worker_command(args),
            args.backend,
            read_json(args.config),
            timeout=args.timeout,
        )
    elif args.operation == "audit":
        episode = Episode(args.episode)
        report = {
            "steps": len(list(episode.transitions())),
            "status": episode.metadata["status"],
            "public_files": list(public_files(args.episode)),
        }
    else:
        actions = json_value(args.actions.read_text(encoding="utf-8"))
        if type(actions) is not list or any(
            type(value) is not dict or not value for value in actions
        ):
            raise ValueError("Actions file must contain an array of nonempty command objects")
        path = collect(
            args.output,
            worker_command(args),
            args.backend,
            read_json(args.config),
            actions,
            seed=args.seed,
            max_steps=args.max_steps,
            timeout=args.timeout,
            references=args.references,
            evaluate=args.evaluate,
            state_language=args.smsl,
        )
        report = {"episode": str(path)}
    print(json.dumps(report, indent=2))
