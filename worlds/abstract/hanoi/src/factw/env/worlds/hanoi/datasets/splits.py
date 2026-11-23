from collections.abc import Collection
from itertools import product
from random import Random

from factw.env.worlds.hanoi import HanoiState, Move, apply_move, legal_moves


def internal_moves(state: HanoiState, allowed: Collection[HanoiState]) -> tuple[Move, ...]:
    """Legal moves whose source and successor both belong to the split."""
    if state not in allowed:
        return ()
    return tuple(move for move in legal_moves(state) if apply_move(state, move) in allowed)


def _grow(available: set[HanoiState], graph, rng: Random) -> set[HanoiState]:
    start = rng.choice(sorted(available, key=lambda state: state.pegs))
    region = {start}
    frontier = graph[start] & available - region
    while len(region) < 5 and frontier:
        state = rng.choice(sorted(frontier, key=lambda state: state.pegs))
        region.add(state)
        frontier = (frontier | graph[state]) & available - region
    return region


def _connected(region: set[HanoiState], graph) -> bool:
    pending = [next(iter(region))]
    reached = set(pending)
    while pending:
        neighbors = graph[pending.pop()] & region - reached
        reached.update(neighbors)
        pending.extend(neighbors)
    return reached == region


def split_states(seed: int = 0) -> dict[str, tuple[HanoiState, ...]]:
    """Partition three-disk Hanoi into connected train/validation/test sets of 17/5/5.

    Training retains every peg value per disk and internal legal moves for every disk.
    Membership is reproducible from the seed; states are sorted by their peg tuples.
    """
    if type(seed) is not int:
        raise ValueError("seed must be an integer")
    rng = Random(seed)
    states = {HanoiState(pegs) for pegs in product(range(3), repeat=3)}
    graph = {state: {apply_move(state, move) for move in legal_moves(state)} for state in states}
    for _ in range(10_000):
        validation = _grow(states, graph, rng)
        test = _grow(states - validation, graph, rng)
        train = states - validation - test
        if len(validation) != 5 or len(test) != 5 or not _connected(train, graph):
            continue
        if any({state.pegs[disk] for state in train} != {0, 1, 2} for disk in range(3)):
            continue
        if {move.disk for state in train for move in internal_moves(state, train)} != {0, 1, 2}:
            continue
        return {
            name: tuple(sorted(region, key=lambda state: state.pegs))
            for name, region in (("train", train), ("validation", validation), ("test", test))
        }
    raise RuntimeError(f"could not find a valid Hanoi state partition for seed {seed}")
