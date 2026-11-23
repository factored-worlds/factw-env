"""Collect, inspect and explicitly export demonstration streams."""

import hashlib
from pathlib import Path


def add_commands(commands):
    parser = commands.add_parser(
        "demonstration", help="Record and export granted demonstration streams"
    )
    operations = parser.add_subparsers(dest="demonstration_operation", required=True)
    record = operations.add_parser("record", help="Collect one reference-assisted teaching episode")
    record.add_argument("--worker-python", type=Path, required=True)
    record.add_argument("--output", type=Path, required=True)
    record.add_argument("--seed", type=int, default=0)
    record.add_argument("--start", type=int, default=0)
    record.add_argument("--max-steps", type=int, default=500)
    record.add_argument("--max-skill-steps", type=int, default=80)
    record.add_argument("--include-commands", action="store_true")
    record.add_argument(
        "--text", type=Path, help="Explicit authored language observations, never private narration"
    )
    for name in ("inspect", "export"):
        operation = operations.add_parser(name)
        operation.add_argument("demonstration", type=Path)
        operation.add_argument("--text", action="store_true", help="Enable the UTF-8 text adapter")
        operation.add_argument(
            "--rgb", action="store_true", help="Enable the raw HWC uint8 RGB adapter"
        )
        if name == "export":
            operation.add_argument("--goal", type=Path, required=True)
            operation.add_argument("--output", type=Path, required=True)
            operation.add_argument("--request-id", default="doom_demonstration")
            operation.add_argument(
                "--prior-smsl",
                type=Path,
                action="append",
                default=[],
                help="Explicit model/task SMSL prior; repeat for several models",
            )


def handle(args):
    if args.demonstration_operation == "record":
        from .teacher import record_demonstration

        runtime = args.worker_python.absolute()
        runtime.stat()
        return record_demonstration(
            args.output,
            (str(runtime), "-m", "factw.env.workers.farama"),
            seed=args.seed,
            start=args.start,
            max_steps=args.max_steps,
            max_skill_steps=args.max_skill_steps,
            include_commands=args.include_commands,
            text=None if args.text is None else args.text.read_text(encoding="utf-8"),
        )
    from .demonstrations import (
        StreamCapabilities,
        export_request,
        read_demonstration,
        write_request_export,
    )

    demonstration = read_demonstration(
        args.demonstration, capabilities=StreamCapabilities(text=args.text, rgb=args.rgb)
    )
    if args.demonstration_operation == "inspect":
        return {
            "source_assistance": demonstration.source_assistance,
            "streams": [
                {
                    "id": stream.id,
                    "modality": stream.modality,
                    "encoding": stream.encoding,
                    "samples": len(stream.samples),
                    "gaps": len(stream.gaps),
                }
                for stream in demonstration.streams
            ],
            "commands": None if demonstration.commands is None else len(demonstration.commands),
            "facts": None
            if demonstration.existing_facts is None
            else len(demonstration.existing_facts),
        }
    priors = []
    for index, path in enumerate(args.prior_smsl):
        source = path.read_text(encoding="utf-8")
        priors.append(
            {
                "id": f"prior_{index}",
                "role": "model",
                "serialization": "smsl_json" if source.lstrip().startswith("{") else "smsl_text",
                "source": source,
                "sha256": hashlib.sha256(source.encode("utf-8")).hexdigest(),
            }
        )
    exported = export_request(
        demonstration,
        request_id=args.request_id,
        original_goal=args.goal.read_bytes(),
        prior_smsl_documents=priors,
    )
    write_request_export(args.output, exported)
    return {
        "request": str(args.output / "request.json"),
        "assets": len(exported.assets),
        "coverage": exported.coverage,
    }
