from collections import deque

from factw.env.worlds.hanoi.state import HanoiState, Move


def is_legal(state: HanoiState, move: Move) -> bool:
    if not isinstance(move, Move) or move.disk >= len(state.pegs):
        raise ValueError("move must identify a disk in this state")
    source = state.pegs[move.disk]
    return move.target != source and all(
        peg not in (source, move.target) for peg in state.pegs[: move.disk]
    )


def legal_moves(state: HanoiState) -> tuple[Move, ...]:
    candidates = (Move(disk, target) for disk in range(len(state.pegs)) for target in range(3))
    return tuple(move for move in candidates if is_legal(state, move))


def apply_move(state: HanoiState, move: Move) -> HanoiState:
    if not is_legal(state, move):
        raise ValueError("illegal Hanoi move")
    pegs = list(state.pegs)
    pegs[move.disk] = move.target
    return HanoiState(tuple(pegs))


def solve(start: HanoiState, goal: HanoiState) -> list[Move]:
    """Find a shortest plan in the three-peg state graph."""
    if len(start.pegs) != len(goal.pegs):
        raise ValueError("start and goal must have the same disk count")
    parents = {start: None}
    queue = deque([start])
    while queue:
        state = queue.popleft()
        if state == goal:
            break
        for move in legal_moves(state):
            successor = apply_move(state, move)
            if successor not in parents:
                parents[successor] = (state, move)
                queue.append(successor)
    else:
        raise RuntimeError("Hanoi goal is unreachable")
    plan = []
    state = goal
    while parents[state] is not None:
        state, move = parents[state]
        plan.append(move)
    return plan[::-1]
