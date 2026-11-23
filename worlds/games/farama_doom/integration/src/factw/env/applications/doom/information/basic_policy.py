"""Closed Basic policy input derived from grounded facts and native pose."""

from copy import deepcopy
from math import isfinite


def policy_input(*, facts, position_y, capture_id, access_sha256, basis):
    if (
        type(facts) is not dict
        or set(facts) != {"active", "alive", "ammo", "won"}
        or any(type(value) is not bool for value in facts.values())
    ):
        raise ValueError("Doom Basic policy requires its four grounded Boolean facts")
    if type(position_y) not in (int, float) or not isfinite(position_y):
        raise ValueError("Doom Basic policy requires a finite native lateral position")
    if (
        type(capture_id) is not str
        or not capture_id
        or type(access_sha256) is not str
        or len(access_sha256) != 64
        or type(basis) is not dict
        or set(basis) != {"revision", "tick"}
        or type(basis["revision"]) is not str
        or not basis["revision"]
        or type(basis["tick"]) is not int
        or basis["tick"] < 0
    ):
        raise ValueError("Doom Basic policy requires capture, access policy and basis provenance")
    return deepcopy(
        {
            "facts": facts,
            "position_y": position_y,
            "provenance": {
                "capture_id": capture_id,
                "access_sha256": access_sha256,
                "basis": basis,
            },
        }
    )
