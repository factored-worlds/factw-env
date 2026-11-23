import argparse
from pathlib import Path

from factw.env.worlds.hanoi.datasets.diagnostics.export import export_audit

parser = argparse.ArgumentParser()
parser.add_argument("--dataset", type=Path, required=True)
parser.add_argument("--output", type=Path, required=True)
parser.add_argument("--styles", type=int, default=32)
parser.add_argument("--seed", type=int, default=1_000_000)
args = parser.parse_args()
result = export_audit(args.dataset, args.output, args.styles, args.seed)
print(
    {
        "appearance": len(result["appearance"]),
        "transitions": len(result["transitions"]),
        "coverage": result["coverage"],
    }
)
