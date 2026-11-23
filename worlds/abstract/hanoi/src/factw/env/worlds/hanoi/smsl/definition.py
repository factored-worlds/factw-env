from dataclasses import replace
from functools import cache
from importlib.resources import files

from factw.env.worlds.hanoi import Move

import smsl

BRANCH = "Hanoi"
FACTS = ("small_peg", "medium_peg", "large_peg")
PEGS = {"a": 0, "b": 1, "c": 2}
OPERATIONS = {
    Move(disk, target): f"move_{name}_{peg}"
    for disk, name in enumerate(("small", "medium", "large"))
    for target, peg in enumerate(PEGS)
}


def pegs(values: dict) -> tuple[int, ...]:
    return tuple(PEGS[values[fact]] for fact in FACTS)


@cache
def machine(start: tuple[int, ...]) -> smsl.Machine:
    source = files("factw.env.worlds.hanoi").joinpath("scenarios/transfer_tower/smsl/hanoi.smsl")
    original = smsl.loads(source.read_text(encoding="utf-8"))
    definition = smsl.Definition.from_machine(original)
    selected = {fact: "abc"[peg] for fact, peg in zip(FACTS, start, strict=True)}
    customized = replace(
        definition.branches[0],
        facts=tuple(
            replace(fact, initial=selected[fact.name]) for fact in definition.branches[0].facts
        ),
    )
    return smsl.compile(replace(definition, branches=(customized,)))
