from importlib.resources import files

import smsl
from factw.env.core.core import StepResult

_GO_TERMINAL = {"black_won", "white_won", "draw"}
_CHESS_TERMINAL = {
    "checkmate",
    "stalemate",
    "insufficient_material",
    "seventyfive_moves",
    "fivefold_repetition",
    "draw_claimed",
}


class TurnMonitor:
    """One composed SMSL instance tracks supplied turn, boundary and acceptance facts."""

    def __init__(
        self,
        game: str,
        player: str,
        *,
        terminated: bool = False,
        truncated: bool = False,
        scope: str = "board-game",
    ):
        if game not in {"go", "chess"}:
            raise ValueError("Expected go or chess")
        self.machine = smsl.loads(files(__package__).joinpath("smsl", "turn.smsl").read_text())
        self.snapshot = self.machine.start(smsl.Context(scope, game, "attempt"))
        payload = self._payload(player, terminated, truncated)
        event = smsl.Event("initialized", 0, self.snapshot.context, payload=payload)
        self.snapshot = self.snapshot.advance(event).snapshot

    @classmethod
    def from_go(cls, env, *, scope="go"):
        if env.attempts != 0:
            raise ValueError("Create the monitor before the first attempt, or restore its archive")
        return cls(
            "go",
            "black" if env.state.player == 1 else "white",
            terminated=env.terminated,
            truncated=env.truncated,
            scope=scope,
        )

    @classmethod
    def from_chess(cls, env, *, scope="chess"):
        if env.attempts != 0:
            raise ValueError("Create the monitor before the first attempt, or restore its archive")
        return cls(
            "chess",
            "white" if env.board.turn else "black",
            terminated=env.terminated,
            truncated=env.truncated,
            scope=scope,
        )

    @property
    def attempts(self) -> int:
        return self.snapshot.step - 1

    def observe_go(self, env, result: StepResult) -> None:
        self._aligned("go", env, result)
        if result.outcome not in _GO_TERMINAL | {"played", "passed", "illegal"}:
            raise ValueError("Unknown Go outcome")
        if result.terminated != (result.outcome in _GO_TERMINAL):
            raise ValueError("Go boundary disagrees with outcome")
        self.observe(
            player="black" if env.state.player == 1 else "white",
            accepted=result.outcome != "illegal",
            terminated=result.terminated,
            truncated=result.truncated,
            attempt=env.attempts,
            turn_changed=result.outcome != "illegal",
        )

    def observe_chess(self, env, result: StepResult) -> None:
        self._aligned("chess", env, result)
        if result.outcome not in _CHESS_TERMINAL | {"moved", "illegal", "claim_denied"}:
            raise ValueError("Unknown chess outcome")
        if result.terminated != (result.outcome in _CHESS_TERMINAL):
            raise ValueError("Chess boundary disagrees with outcome")
        accepted = result.outcome not in {"illegal", "claim_denied"}
        self.observe(
            player="white" if env.board.turn else "black",
            accepted=accepted,
            terminated=result.terminated,
            truncated=result.truncated,
            attempt=env.attempts,
            turn_changed=accepted and result.outcome != "draw_claimed",
        )

    def _aligned(self, game, env, result):
        if self.snapshot.context.subject != game:
            raise ValueError("Monitor belongs to another game")
        if (env.last_outcome, env.terminated, env.truncated) != (
            result.outcome,
            result.terminated,
            result.truncated,
        ):
            raise ValueError("Supplied result differs from the engine's completed outcome")

    def observe(
        self,
        *,
        player: str,
        accepted: bool,
        terminated: bool,
        truncated: bool,
        attempt: int,
        turn_changed: bool,
    ) -> None:
        if self.facts()["game_over"]:
            raise RuntimeError("Cannot observe another attempt after a game boundary")
        if type(attempt) is not int or attempt != self.attempts + 1:
            raise ValueError("Monitor attempts must follow consecutive completed outcomes")
        if type(accepted) is not bool or type(turn_changed) is not bool:
            raise ValueError("Acceptance and turn change must be Boolean")
        payload = self._payload(player, terminated, truncated)
        if (payload["black_turn"] != self.facts()["black_turn"]) != turn_changed:
            raise ValueError("Observed player disagrees with reported turn change")
        if not accepted and turn_changed:
            raise ValueError("A rejected attempt must preserve the player")
        event = smsl.Event(
            "observed", attempt, self.snapshot.context, payload={**payload, "accepted": accepted}
        )
        self.snapshot = self.snapshot.advance(event).snapshot

    def facts(self) -> dict:
        return {
            **self.snapshot.facts("Turn"),
            **self.snapshot.facts("Game"),
            **self.snapshot.facts("LastAction"),
        }

    def to_json(self) -> str:
        return self.snapshot.to_json()

    @classmethod
    def restore(cls, source: str):
        result = cls("go", "black")
        snapshot = result.machine.restore(source)
        if snapshot.context.subject not in {"go", "chess"} or snapshot.step < 1:
            raise ValueError("Invalid board-game monitor archive")
        result.snapshot = snapshot
        return result

    @staticmethod
    def _payload(player, terminated, truncated):
        if player not in {"black", "white"}:
            raise ValueError("Player must be black or white")
        if (
            type(terminated) is not bool
            or type(truncated) is not bool
            or (terminated and truncated)
        ):
            raise ValueError("Invalid board-game boundary")
        return {"black_turn": player == "black", "terminated": terminated, "truncated": truncated}
