from collections import deque
from random import Random

from factw.env.worlds.hanoi import HanoiState, HanoiTask, Move, apply_move, is_legal
from factw.env.worlds.hanoi.datasets.splits import internal_moves


def path_within(start: HanoiState, goal: HanoiState, allowed: frozenset[HanoiState]) -> list[Move]:
    queue = deque([(start, [])])
    seen = {start}
    while queue:
        state, path = queue.popleft()
        if state == goal:
            return path
        for move in internal_moves(state, allowed):
            successor = apply_move(state, move)
            if successor not in seen:
                seen.add(successor)
                queue.append((successor, [*path, move]))
    raise ValueError("Goal is unreachable within the configuration split")


def illegal_moves(state: HanoiState) -> tuple[Move, ...]:
    candidates = (Move(disk, target) for disk in range(3) for target in range(3))
    return tuple(move for move in candidates if not is_legal(state, move))


def episode_plan(
    start: HanoiState,
    allowed: frozenset[HanoiState],
    rng: Random,
    max_steps: int,
    visit: int,
) -> tuple[HanoiTask, list[Move]]:
    moves = sorted(internal_moves(start, allowed), key=lambda move: (-move.disk, move.target))
    first = moves[visit % len(moves)]
    first_successor = apply_move(start, first)
    goals = [
        state
        for state in sorted(allowed, key=lambda state: state.pegs)
        if state not in (start, first_successor)
        and len(path_within(start, state, allowed)) <= max_steps - 3
    ]
    goal = rng.choice(goals)
    actions = [rng.choice(illegal_moves(start)), first, Move(first.disk, start.pegs[first.disk])]
    state = start
    while state != goal:
        remaining = max_steps - len(actions)
        path = path_within(state, goal, allowed)
        if remaining > len(path) and rng.random() < 0.2:
            actions.append(rng.choice(illegal_moves(state)))
            continue
        candidates = [
            move
            for move in internal_moves(state, allowed)
            if len(path_within(apply_move(state, move), goal, allowed)) < remaining
        ]
        move = rng.choice(candidates) if rng.random() < 0.5 else path[0]
        actions.append(move)
        state = apply_move(state, move)
    return HanoiTask(start.pegs, goal.pegs, max_steps), actions
