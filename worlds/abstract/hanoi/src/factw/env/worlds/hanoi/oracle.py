from factw.env.worlds.hanoi.state import HanoiState


class HanoiOracle:
    """Privileged annotations, kept separate from observations."""

    def describe(self, state: HanoiState) -> dict:
        return {
            "annotator": "hanoi",
            "version": 1,
            "entity_ids": [f"disk_{disk}" for disk in range(len(state.pegs))],
            "pegs": list(state.pegs),
            "clear": [peg not in state.pegs[:disk] for disk, peg in enumerate(state.pegs)],
        }

    def compare(self, before: HanoiState, after: HanoiState) -> dict:
        if len(before.pegs) != len(after.pegs):
            raise ValueError("states must have the same disk count")
        changes = [
            {"disk": disk, "source": source, "target": target}
            for disk, (source, target) in enumerate(zip(before.pegs, after.pegs, strict=True))
            if source != target
        ]
        return {"changed_disks": [change["disk"] for change in changes], "changes": changes}
