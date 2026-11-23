import argparse
import json
from pathlib import Path

from factw.env.worlds.hanoi.datasets.generate import generate_dataset


def main():
    parser = argparse.ArgumentParser(description="Generate a configuration-disjoint Hanoi dataset")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument(
        "--episodes", type=int, nargs=3, default=(128, 32, 32), metavar=("TRAIN", "VAL", "TEST")
    )
    parser.add_argument("--max-steps", type=int, default=16)
    parser.add_argument("--collection-seed", type=int)
    parser.add_argument("--style-seed", type=int)
    args = parser.parse_args()
    manifest = generate_dataset(
        args.output,
        args.seed,
        tuple(args.episodes),
        args.max_steps,
        collection_seed=args.collection_seed,
        style_seed=args.style_seed,
    )
    print(
        json.dumps(
            {
                "output": str(args.output),
                "episodes": {name: len(paths) for name, paths in manifest["splits"].items()},
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
