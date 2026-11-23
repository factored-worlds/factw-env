"""Generate an inspectable hypothesis from an explicitly granted demonstration."""

import os
from pathlib import Path


def add_command(commands):
    command = commands.add_parser(
        "discover", help="Propose SMSL from granted demonstration streams"
    )
    command.add_argument("--request-export", type=Path, required=True)
    command.add_argument("--original-goal", type=Path, required=True)
    command.add_argument("--provider", choices=("openai",), required=True)
    command.add_argument("--model", required=True, help="Explicit supported model snapshot")
    command.add_argument("--condition-id", required=True)
    command.add_argument("--ledger", type=Path, required=True, help="Persistent condition budget")
    command.add_argument("--output", type=Path, required=True, help="New discovery audit directory")
    command.add_argument("--api-key-env", default="OPENAI_API_KEY")
    inspect = commands.add_parser(
        "composition", help="Check an explicit RGB composition without a model or native run"
    )
    inspect.add_argument("--request-export", type=Path, required=True)
    inspect.add_argument("--original-goal", type=Path, required=True)
    inspect.add_argument("--candidate", type=Path, required=True)
    inspect.add_argument("--primitives", type=Path, required=True)


def inspect_composition(args):
    from ..refinement.export import read_granted_request
    from .refinement_composition import prepare_composition, primitive_bindings

    request = read_granted_request(args.request_export, args.original_goal)
    primitives = primitive_bindings(args.primitives.read_bytes())
    return prepare_composition(request, args.candidate.read_bytes(), primitives).describe()


def handle(args):
    from ..providers.model_transport import ModelConfiguration, openai_transport
    from ..providers.symbolic.discovery.refinement import ModelRefinementProvider
    from ..refinement.export import read_granted_request

    if args.output.exists() or args.output.is_symlink():
        raise FileExistsError(args.output)
    request = read_granted_request(args.request_export, args.original_goal)
    configuration = ModelConfiguration(
        provider=args.provider,
        model=args.model,
        condition_id=args.condition_id,
        ledger_path=args.ledger,
    )
    key = os.environ.get(args.api_key_env)
    if not key:
        raise ValueError(f"Missing model credential in {args.api_key_env}")
    with openai_transport(configuration, api_key=key) as transport:
        result = ModelRefinementProvider(transport).discover(request, audit_directory=args.output)
    return {
        "audit_directory": str(result.audit_directory),
        "attempts": result.attempts,
        "valid": result.valid,
        "ready": result.review.ready if result.review is not None else False,
        "executed": False,
        "goal_success_claimed": False,
    }
