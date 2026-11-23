"""Run or replay the articulated Robot Hanoi simulator."""

import argparse
import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4


def _runs():
    return Path(os.environ.get("FACTW_RUNS_DIR", "outputs/worlds")) / "robotic.mujoco-hanoi"


def _new_run(mode):
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    return _runs() / f"{mode}_{stamp}_{uuid4().hex[:8]}"


def _latest_run():
    reports = list(_runs().glob("*/report.json"))
    if not reports:
        raise ValueError("Record a player or agent run first")
    return max(reports, key=lambda report: (report.stat().st_mtime_ns, report)).parent


def _solve(session):
    session.frame()
    while session.next_agent_move():
        session.frame()
        intervals = 0
        while session.advance():
            intervals += 1
            if intervals % 3 == 0:
                session.frame()
        session.frame()
    return 0 if session.solved else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="mode", required=True)
    commands.add_parser("check", help="Verify the simulator and State Language installation")
    play = commands.add_parser("play", help="Choose a disk and a destination peg")
    agent = commands.add_parser("agent", help="Watch the robot solve the puzzle")
    for command in (play, agent):
        command.add_argument("--output", type=Path, help="Save into a new run directory")
    agent.add_argument("--seed", type=int, metavar="N", help="Repeat an agent board and goal")
    agent.add_argument("--headless", action="store_true", help="Record without a desktop window")
    replay = commands.add_parser("replay", help="Review a recorded camera and its SMSL facts")
    replay.add_argument("run", type=Path, nargs="?")
    replay.add_argument("--no-open", action="store_true")
    args = parser.parse_args()

    if args.mode == "replay":
        from .replay import replay_run

        try:
            path = replay_run(args.run or _latest_run(), open_page=not args.no_open)
        except ValueError as error:
            parser.error(str(error))
        print(path)
        return 0

    from ..robot import RobotHanoi
    from .episode import Episode
    from .session import HanoiSession

    if args.mode == "check":
        robot = RobotHanoi()
        try:
            robot.reset()
            state = robot.settled_state()
            if state is None or state.pegs != (0, 0, 0):
                raise ValueError("The starting Hanoi tower did not settle")
        finally:
            robot.close()
        print("Robot Hanoi is ready")
        return 0

    desktop = bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))
    if args.mode == "play" and not desktop:
        parser.error("Robot Hanoi play requires a desktop display")
    headless = args.mode == "agent" and (args.headless or not desktop)
    output = (args.output or _new_run(args.mode)).absolute()
    if output.exists() or output.is_symlink():
        parser.error(f"Run directory already exists: {output}")
    try:
        episode = Episode.sample(args.seed) if args.mode == "agent" else Episode()
    except ValueError as error:
        parser.error(str(error))
    if episode.seed is not None:
        start = ", ".join("ABC"[peg] for peg in episode.task.start)
        goal = "ABC"[episode.task.goal[0]]
        print(f"Seed {episode.seed} · small, medium, large on {start} · build the tower on {goal}")
    print(f"Recording to {output}", flush=True)
    try:
        with HanoiSession(RobotHanoi(), output, mode=args.mode, episode=episode) as session:
            if headless:
                result = _solve(session)
            else:
                from ..desktop import run_desktop

                run_desktop(session)
                result = int(session.failed)
            print(session.status)
    except KeyboardInterrupt:
        return 130
    return result


if __name__ == "__main__":
    raise SystemExit(main())
