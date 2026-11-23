import argparse
import os
import sys

from .protocol import serve
from .registry import backend_names


def main():
    parser = argparse.ArgumentParser(description="Run an isolated Farama environment worker")
    parser.add_argument("--list-backends", action="store_true")
    args = parser.parse_args()
    if args.list_backends:
        print("\n".join(backend_names()))
        return
    with os.fdopen(os.dup(sys.stdout.fileno()), "w", encoding="utf-8") as output:
        os.dup2(sys.stderr.fileno(), sys.stdout.fileno())
        sys.stdout = sys.stderr
        serve(sys.stdin, output)
