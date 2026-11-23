import math
import re

INTERFACES = {
    "benchmark-command-v1",
    "go-command-v1",
    "chess-command-v1",
    "wordle-guess-v1",
    "arena-action-v1",
    "pusht-target-v1",
}
ENGINE_INTERFACES = {
    "go-tromp-taylor-v1": "go-command-v1",
    "chess-standard-v1": "chess-command-v1",
    "wordle-v1": "wordle-guess-v1",
    "isaaclab-arena-v1": "arena-action-v1",
    "pusht-v1": "pusht-target-v1",
}


def validate_action(value: dict, interface: str) -> None:
    match interface:
        case "benchmark-command-v1":
            _keys(value, {"command"})
            if type(value["command"]) is not dict or not value["command"]:
                raise ValueError("Benchmark command must be a nonempty JSON object")
        case "go-command-v1":
            _keys(value, {"operation", "row", "column"})
            if value["operation"] == "pass":
                if value["row"] is not None or value["column"] is not None:
                    raise ValueError("Go pass cannot contain coordinates")
            elif value["operation"] == "play":
                if any(
                    type(value[k]) is not int or not 0 <= value[k] < 19 for k in ("row", "column")
                ):
                    raise ValueError("Go coordinates must be integers from 0 through 18")
            else:
                raise ValueError("Unknown Go operation")
        case "chess-command-v1":
            _keys(value, {"operation", "source", "target", "promotion"})
            if value["operation"] not in ("move", "claim_draw"):
                raise ValueError("Unknown chess operation")
            if (
                value["operation"] == "claim_draw"
                and value["source"] is None
                and value["target"] is None
            ):
                if value["promotion"] is not None:
                    raise ValueError("Draw claim promotion requires an intended move")
                return
            if any(
                type(value[k]) is not str or re.fullmatch("[a-h][1-8]", value[k]) is None
                for k in ("source", "target")
            ):
                raise ValueError("Chess squares must use a1 through h8")
            if value["promotion"] not in (None, "q", "r", "b", "n"):
                raise ValueError("Invalid chess promotion")
        case "wordle-guess-v1":
            _keys(value, {"guess"})
            if type(value["guess"]) is not str or re.fullmatch("[A-Z]{5}", value["guess"]) is None:
                raise ValueError("Wordle guesses must contain five uppercase ASCII letters")
        case "pusht-target-v1":
            _keys(value, {"x", "y"})
            if any(
                type(value[key]) not in (int, float) or not 0 <= value[key] <= 512
                for key in ("x", "y")
            ):
                raise ValueError("Push-T target coordinates must be finite numbers in [0, 512]")
        case "arena-action-v1":
            _keys(value, {"values"})
            if type(value["values"]) is not list or not value["values"]:
                raise ValueError("Arena action must contain a nonempty vector")
            if any(type(x) not in (int, float) or not math.isfinite(x) for x in value["values"]):
                raise ValueError("Arena action coordinates must be finite numbers")
        case _:
            raise ValueError("Unknown domain action interface")


def _keys(value: dict, expected: set[str]) -> None:
    if type(value) is not dict or set(value) != expected:
        raise ValueError("Invalid domain action fields")
