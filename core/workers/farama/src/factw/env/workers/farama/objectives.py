"""Explicit projections for the host's scalar reward boundary."""

import math

import numpy as np


class RewardProjection:
    def __init__(self, config: dict, *, multiagent: bool, multiobjective: bool):
        required = set()
        if multiagent:
            required.add("agent_reduction")
        if multiobjective:
            required.add("objective_weights")
        if not isinstance(config, dict) or config.keys() != required:
            raise ValueError(f"reward_projection must contain exactly {sorted(required)}")
        self.config = dict(config)
        self.reduction = config.get("agent_reduction")
        if multiagent and self.reduction not in {"sum", "mean"}:
            raise ValueError("agent_reduction must be sum or mean")
        self.weights = None
        if multiobjective:
            weights = config["objective_weights"]
            if (
                not isinstance(weights, list)
                or not weights
                or any(type(value) not in {int, float} for value in weights)
            ):
                raise ValueError("objective_weights must be a nonempty numeric list")
            self.weights = np.asarray(weights, dtype=np.float64)
            if not np.isfinite(self.weights).all():
                raise ValueError("objective_weights must be finite")

    def scalar(self, reward) -> float:
        native = np.asarray(reward)
        if native.dtype.kind not in "iuf" or not np.isfinite(native).all():
            raise ValueError("native rewards must be finite numbers")
        if self.weights is None:
            if native.shape != ():
                raise ValueError("expected a scalar native reward")
            result = float(native)
        else:
            if native.shape != self.weights.shape:
                raise ValueError("native reward dimensions do not match objective_weights")
            result = float(np.dot(native, self.weights))
        if not math.isfinite(result):
            raise ValueError("projected reward is not finite")
        return result

    def agents(self, rewards: dict) -> float:
        values = [self.scalar(reward) for reward in rewards.values()]
        total = math.fsum(values)
        if self.reduction == "mean" and values:
            return total / len(values)
        return total
