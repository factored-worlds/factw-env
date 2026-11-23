import argparse
import json
from contextlib import ExitStack
from dataclasses import asdict
from importlib.util import find_spec
from pathlib import Path
from uuid import uuid4

from factw.env.core.recording import EpisodeWriter
from factw.env.worlds.hanoi import (
    HanoiEnv,
    HanoiOracle,
    HanoiState,
    HanoiTask,
    __version__,
    solve,
)


def symbolic_rollout(env):
    for action in solve(env.state, HanoiState(env.task.goal)):
        yield action, env.step(action)


def record_demo(args) -> dict:
    if args.backend == "mujoco" and find_spec("factw.env.worlds.mujoco_hanoi") is None:
        raise RuntimeError(
            "MuJoCo Hanoi is not installed. Use the 'mujoco-hanoi' Pixi environment "
            "or install factored-worlds-mujoco-hanoi."
        )
    task = HanoiTask(
        start=tuple("abc".index(peg) for peg in args.start),
        goal=tuple("abc".index(peg) for peg in args.goal),
    )
    args.output.mkdir(parents=True)
    task_id = uuid4().hex
    with ExitStack() as stack:
        if args.backend == "symbolic":
            engine_version = __version__
            env = HanoiEnv(task)

            def state():
                return env.state

            rollout = symbolic_rollout(env)
            action_interface = "disk-target-v1"
        else:
            from factw.env.worlds.mujoco_hanoi import __version__ as engine_version
            from factw.env.worlds.mujoco_hanoi.controller import GantryController
            from factw.env.worlds.mujoco_hanoi.hanoi import MujocoHanoiEnv

            env = stack.enter_context(MujocoHanoiEnv(task, width=args.width, height=args.height))
            state = env.physical_state
            rollout = GantryController(env).solve()
            action_interface = "cartesian-jaw-setpoint-v1"
        initial = env.reset(seed=args.seed)
        writer = stack.enter_context(
            EpisodeWriter(
                args.output / "episode",
                initial,
                engine_version=engine_version,
                engine=f"hanoi-{args.backend}-v1",
                action_interface=action_interface,
                seed=args.seed,
                task_id=task_id,
                initial_terminated=env.terminated if args.backend == "symbolic" else env.solved,
            )
        )
        oracle = stack.enter_context((args.output / "oracle.jsonl").open("x"))

        def annotate():
            physical = state()
            reference = None if physical is None else HanoiOracle().describe(physical)
            record = {"step": writer.index, "reference": reference}
            oracle.write(json.dumps(record) + "\n")

        config = {
            "task_id": task_id,
            "episode_id": writer.manifest["episode_id"],
            "task": asdict(task),
            "oracle": "oracle.jsonl",
        }
        (args.output / "task.json").write_text(json.dumps(config, indent=2) + "\n")
        annotate()
        for action, result in rollout:
            writer.append(asdict(action), result)
            annotate()
            if result.terminated or result.truncated:
                break
    return {
        "episode": str(writer.path),
        "steps": writer.index,
        "simulated_seconds": round(writer.time, 6),
        "status": writer.manifest["status"],
    }


def main():
    parser = argparse.ArgumentParser(description="Record a Hanoi demonstration")
    parser.add_argument("--backend", choices=("symbolic", "mujoco"), default="symbolic")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--start", default="aaa", help="Smallest-to-largest disk pegs, using a/b/c")
    parser.add_argument("--goal", default="ccc")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--width", type=int, default=160)
    parser.add_argument("--height", type=int, default=120)
    report = record_demo(parser.parse_args())
    print(json.dumps(report, indent=2))
    if report["status"] != "terminated":
        raise SystemExit("Demonstration did not reach its goal")
