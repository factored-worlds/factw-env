"""Admit one Hanoi move and confirm its state change after physical placement."""

from contextlib import ExitStack
from dataclasses import asdict
from uuid import uuid4

from factw.env.worlds.hanoi import HanoiState, Move, apply_move, is_legal, solve
from factw.env.worlds.hanoi.smsl.definition import pegs
from factw.env.worlds.mujoco_hanoi.robot import TransferError
from factw.env.worlds.mujoco_hanoi.showcase.episode import Episode
from factw.env.worlds.mujoco_hanoi.showcase.model import DISKS, RobotMonitor
from factw.env.worlds.mujoco_hanoi.showcase.recording import Recording

SCENARIO_ID = "robotic.mujoco-hanoi/transfer-tower-with-robot"
SCENARIO_REVISION = 3


class HanoiSession:
    control_dt = 1 / 30

    def __init__(self, robot, output, *, mode, episode=None):
        with ExitStack() as startup:
            startup.callback(robot.close)
            if mode not in {"play", "agent"}:
                raise ValueError("Hanoi session mode must be play or agent")
            self.episode = episode or (Episode.sample() if mode == "agent" else Episode())
            task = self.episode.task
            robot.reset(task.start)
            if robot.settled_state() != HanoiState(task.start):
                raise TransferError(
                    "The physical disks did not settle on the selected starting pegs"
                )
            self._monitor = RobotMonitor(task.start, task.goal, f"robot-hanoi-{uuid4().hex}")
            self._recording = Recording(output)
            self._resources = startup.pop_all()
        self._robot = robot
        self.mode = mode
        self.goal = task.goal
        self.phase = "ready"
        self.status = f"Build the tower on peg {'ABC'[self.goal[0]]}."
        self.time = 0.0
        self.grasped = False
        self.moves = 0
        self.active_move = None
        self._motion = None
        self._expected = None
        self.last_changes = {}
        self._closed = False
        self._recording.event(
            "initial",
            self.time,
            fact_step=0,
            facts=self.facts,
            **self.episode.metadata(),
        )

    @property
    def active(self):
        return self.active_move is not None

    @property
    def solved(self):
        return self.phase == "solved"

    @property
    def failed(self):
        return self.phase == "failed"

    @property
    def pegs(self):
        return pegs(self.facts)

    @property
    def facts(self):
        return self._monitor.facts

    def _update(self, name, payload, *, placed=None):
        row = self._monitor.update(name, payload, placed=placed)
        self.last_changes = row["changes"]
        return row

    def _transfer_fields(self, move):
        return {
            "disk": DISKS[move.disk],
            "source_peg": "abc"[self.pegs[move.disk]],
            "target_peg": "abc"[move.target],
        }

    def request(self, disk, target):
        """Admit an ordinary high-level move for either operator."""
        rejection = self._reject(disk, target)
        request = {
            "disk": disk if type(disk) is int else None,
            "target": target if type(target) is int else None,
        }
        if rejection:
            self.status = rejection
            self._recording.event("request", self.time, **request, accepted=False, reason=rejection)
            return False
        move = Move(disk, target)
        board = HanoiState(self.pegs)
        if self._robot.settled_state() != board:
            reason = "The physical board differs from the last confirmed state."
            self._recording.event("request", self.time, **request, accepted=False, reason=reason)
            self._fail(reason)
            return False
        self._expected = apply_move(board, move)
        self._motion = self._robot.move(disk, target)
        update = self._update("transfer_started", self._transfer_fields(move))
        self._recording.event(
            "request",
            self.time,
            **request,
            source=board.pegs[disk],
            accepted=True,
            **update,
        )
        self.active_move = move
        self.phase = "queued"
        self.status = f"Moving disk {disk + 1} from {'ABC'[board.pegs[disk]]} to {'ABC'[target]}."
        return True

    def _reject(self, disk, target):
        if self.active:
            return "Wait for the arm to finish this move."
        if self.solved or self.failed:
            return "Start a fresh session to move again."
        if type(disk) is not int or disk not in range(len(self.pegs)):
            return "Select a disk on the board."
        if type(target) is not int or target not in range(3):
            return "Select a destination peg."
        if not is_legal(HanoiState(self.pegs), Move(disk, target)):
            return "Move the top disk to a different peg with no smaller disk."
        return None

    def next_agent_move(self):
        if self.active or self.solved or self.failed:
            return False
        move = solve(HanoiState(self.pegs), HanoiState(self.goal))[0]
        return self.request(move.disk, move.target)

    def advance(self):
        """Apply one native control interval or finish the checked placement."""
        if not self.active:
            return False
        try:
            sample = next(self._motion)
        except TransferError as error:
            self._fail(str(error))
            return False
        except StopIteration:
            self._confirm()
            return False
        self.time = sample.time
        update = {}
        if sample.phase != self.phase or sample.grasped != self.grasped:
            contact = DISKS[self.active_move.disk] if sample.grasped else "none"
            update = self._update(
                "arm_observed", {"phase": sample.phase.lower(), "contact_disk": contact}
            )
        self.phase = sample.phase
        self.grasped = sample.grasped
        self._recording.control(sample, **update)
        return True

    def _confirm(self):
        observed = self._robot.settled_state()
        if observed != self._expected:
            self._fail("The disk did not settle at the requested position.")
            return
        move = self.active_move
        update = self._update("placement_observed", self._transfer_fields(move), placed=move)
        self.moves += 1
        if self.pegs != observed.pegs:
            raise RuntimeError("SMSL state disagrees with the confirmed native placement")
        self.phase = "solved" if observed.pegs == self.goal else "placed"
        target = "ABC"[move.target]
        self.status = f"Placed disk {move.disk + 1} on peg {target}."
        if self.solved:
            self.status = f"Tower moved in {self.moves} placed moves."
        self._recording.event(
            "placement",
            self.time,
            **asdict(move),
            **update,
            observed_pegs=observed.pegs,
            outcome=self.phase,
        )
        self._motion = self.active_move = self._expected = None
        self.grasped = False
        if self.moves == self.episode.task.max_steps and not self.solved:
            self._fail("Reached the move limit before completing the tower.")

    def _fail(self, message):
        self.phase = "failed"
        self.status = message
        self._recording.event(
            "failed",
            self.time,
            reason=message,
            move=None if self.active_move is None else asdict(self.active_move),
            **self._update("transfer_ended", {"outcome": "failed"}),
        )
        self._motion = self.active_move = self._expected = None

    def frame(self, camera="overview"):
        rgb = self._robot.render(camera)
        self._recording.frame(rgb, camera, self.time)
        return rgb

    def close(self):
        if self._closed:
            return
        self._closed = True
        outcome = self.phase if self.solved or self.failed else "interrupted"
        try:
            update = (
                self._update("transfer_ended", {"outcome": "interrupted"})
                if outcome == "interrupted"
                else {}
            )
            self._recording.event("end", self.time, outcome=outcome, **update)
            self._recording.finish(
                {
                    "mode": self.mode,
                    "scenario_id": SCENARIO_ID,
                    "scenario_revision": SCENARIO_REVISION,
                    "backend": "mujoco-simulation",
                    "information_profile": "reference-assisted"
                    if self.mode == "agent"
                    else "human",
                    "camera_source": "mujoco-rgb",
                    "placement_evidence": "settled-native-board",
                    "outcome": outcome,
                    "status": self.status,
                    "moves": self.moves,
                    "simulated_seconds": self.time,
                    **self.episode.metadata(),
                    "last_confirmed_pegs": self.pegs,
                },
                self._monitor.world.to_json(),
            )
        finally:
            self._resources.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
