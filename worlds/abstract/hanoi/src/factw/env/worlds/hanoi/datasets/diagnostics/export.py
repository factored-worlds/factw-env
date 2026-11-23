import hashlib
import json
from collections import Counter
from dataclasses import asdict
from itertools import product
from pathlib import Path

from factw.env import core
from factw.env.worlds import hanoi
from factw.env.worlds.hanoi import HanoiState, Move, apply_move, is_legal, sample_style
from factw.env.worlds.hanoi.render import render
from PIL import Image


def _json(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n")


def export_audit(dataset: Path, output: Path, styles: int = 32, seed: int = 1_000_000) -> dict:
    if styles < 1:
        raise ValueError("styles must be positive")
    manifest = json.loads((dataset / "dataset.json").read_text())
    private = json.loads((dataset / "privileged/index.json").read_text())
    partitions = {name: {tuple(s) for s in states} for name, states in private["splits"].items()}
    membership = {state: name for name, states in partitions.items() for state in states}
    training = set()
    for relative in manifest["splits"]["train"]:
        annotation = private["episodes"][relative]["annotations"]
        states = [
            tuple(json.loads(row)["reference"]["pegs"])
            for row in (dataset / annotation).read_text().splitlines()
        ]
        actions = [
            json.loads(row)["action"]
            for row in (dataset / relative / "steps.jsonl").read_text().splitlines()
        ]
        for before, action, after in zip(states[:-1], actions, states[1:], strict=True):
            state, move = HanoiState(before), Move(action["disk"], action["target"])
            expected = apply_move(state, move).pegs if is_legal(state, move) else before
            if after != expected:
                raise ValueError("Recorded training annotation disagrees with engine dynamics")
            training.add((before, action["disk"], action["target"], after))
    old_styles = {
        json.dumps(item["style"], sort_keys=True) for item in private["episodes"].values()
    }
    chosen, candidate = [], seed
    while len(chosen) < styles:
        style = asdict(sample_style(candidate))
        key = json.dumps(style, sort_keys=True)
        if key not in old_styles:
            chosen.append((candidate, style))
            old_styles.add(key)
        candidate += 1
    output.mkdir(parents=True)
    (output / "appearance").mkdir()
    (output / "stress").mkdir()
    appearance = []
    for state in sorted(partitions["train"]):
        for style_seed, _style in chosen:
            relative = f"appearance/{''.join(map(str, state))}-{style_seed}.png"
            Image.fromarray(render(state, sample_style(style_seed))).save(output / relative)
            appearance.append({"state": state, "style_seed": style_seed, "image": relative})
    state_images, transitions = [], []
    for state in product(range(3), repeat=3):
        relative = f"stress/{''.join(map(str, state))}.png"
        Image.fromarray(render(state, sample_style(chosen[0][0]))).save(output / relative)
        state_images.append({"state": state, "image": relative})
        for disk, target in product(range(3), repeat=2):
            before, move = HanoiState(state), Move(disk, target)
            legal = is_legal(before, move)
            after = apply_move(before, move).pegs if legal else state
            if (state, disk, target, after) in training:
                group = "training_covered"
            elif membership[state] != membership[after]:
                group = "crossing"
            elif membership[state] in ("validation", "test"):
                group = "held_out_interior"
            else:
                group = "other_uncovered"
            transitions.append(
                {
                    "state": state,
                    "action": [disk, target],
                    "next_state": after,
                    "legal": legal,
                    "group": group,
                    "source_split": membership[state],
                }
            )
    result = {
        "format": "hanoi-component-audit-v1",
        "dataset": str(dataset.resolve()),
        "dataset_manifest_sha256": hashlib.sha256(
            (dataset / "dataset.json").read_bytes()
        ).hexdigest(),
        "private_index_sha256": hashlib.sha256(
            (dataset / "privileged/index.json").read_bytes()
        ).hexdigest(),
        "styles": [{"seed": s, "style": v} for s, v in chosen],
        "style_disjoint_from_recorded": True,
        "appearance": appearance,
        "state_images": state_images,
        "transitions": transitions,
        "coverage": dict(Counter(row["group"] for row in transitions)),
        "interpretation": "Post-selection development stress audit; no fresh semantic holdout",
    }
    result["package_versions"] = {
        package.__name__: package.__version__ for package in (core, hanoi)
    }
    result["source_sha256"] = {
        f"{package.__name__}/{path.relative_to(directory)}": hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
        for package in (core, hanoi)
        for directory in (Path(package.__file__).parent,)
        for path in sorted(directory.rglob("*"))
        if path.is_file() and "__pycache__" not in path.parts
    }
    result["assets_sha256"] = {
        str(path.relative_to(output)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(output.rglob("*.png"))
    }
    _json(output / "audit.json", result)
    return result
