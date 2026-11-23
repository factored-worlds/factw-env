"""Collect every player capture from one explicitly reference-assisted teacher run."""

import json
from contextlib import ExitStack
from importlib.metadata import version
from pathlib import Path
from time import monotonic
from uuid import uuid4

from factw.env.external.env import connect
from factw.env.worlds.doom.assets import (
    scenario_configuration,
    scenario_directory,
    validate_runtime,
)

from ..evaluation import evaluate
from ..scenarios.retrieve_key_and_escape.session import NavigationSession
from .demonstrations import DemonstrationWriter

SCENARIO = "games.doom/retrieve-key-and-escape"


def record_demonstration(
    output,
    worker_command,
    *,
    seed=0,
    start=0,
    max_steps=500,
    max_skill_steps=80,
    include_commands=False,
    text=None,
):
    """Save granted streams separately from private teacher/evaluator evidence."""
    for value in (max_steps, max_skill_steps):
        if type(value) is not int or value < 1:
            raise ValueError("Teacher action and skill budgets must be positive integers")
    if type(include_commands) is not bool:
        raise ValueError("include_commands must be Boolean")
    if text is not None and (type(text) is not str or not text.strip()):
        raise ValueError("Authored demonstration text must be nonempty UTF-8 text")
    output = Path(output)
    with scenario_directory(SCENARIO) as directory:
        config, manifest = scenario_configuration(
            directory,
            start=start,
            visible=False,
            presentation={
                "render_hud": True,
                "resolution": "RES_320X240",
                "doom_skill": 1,
                "sound_enabled": False,
            },
        )
        output.mkdir(parents=True, exist_ok=False)
        private = output / "privileged"
        private.mkdir()
        (private / "configuration.json").write_text(json.dumps(config, indent=2) + "\n")
        with ExitStack() as resources:
            log = resources.enter_context((private / "worker.log").open("x"))
            env = resources.enter_context(
                connect(worker_command, "vizdoom", config, max_steps=max_steps, stderr=log)
            )
            validate_runtime(env.metadata, manifest)
            session = resources.enter_context(
                NavigationSession(
                    env, scene_spec=manifest["scene_spec"], max_skill_steps=max_skill_steps
                )
            )
            writer = resources.enter_context(
                DemonstrationWriter(
                    output / "demonstration", source_id=uuid4().hex, assistance="reference_assisted"
                )
            )
            session.reset(seed=seed)
            origin = monotonic()
            previous = None
            captures = gaps = steps = 0

            def capture():
                nonlocal previous, captures, gaps
                relative_time = monotonic() - origin
                if session.observation.rgb is None:
                    writer.add_gap(
                        stream_id="player_rgb",
                        after_sample=previous,
                        reason="unavailable_capture",
                        relative_time=relative_time,
                        capture_id=session.boundary.capture_id,
                    )
                    gaps += 1
                    return
                view = session.player_view()
                writer.add_rgb(view, relative_time=relative_time)
                previous = view.capture_id
                captures += 1

            if text is not None:
                writer.add_text(text, sample_id=uuid4().hex, provenance="authored_demonstration")
            capture()
            while steps < max_steps:
                step = session.tick()
                if step is None:
                    break
                steps += 1
                if include_commands:
                    writer.add_command(step.command["buttons"], relative_time=monotonic() - origin)
                capture()
            writer.close()
            evaluation_input = session.boundary.evaluation_inputs()
            (private / "evaluation_input.json").write_text(
                json.dumps(evaluation_input, indent=2) + "\n"
            )
            report = {
                "schema": "doom.teaching-recording/1",
                "scenario_id": SCENARIO,
                "scenario_behavior_revision": 1,
                "seed": seed,
                "start": start,
                "assistance": "reference_assisted",
                "steps": steps,
                "rgb_captures": captures,
                "missing_captures": gaps,
                "commands_recorded": include_commands,
                "text_source": None if text is None else "explicit_authored_demonstration",
                "max_steps": max_steps,
                "max_skill_steps": max_skill_steps,
                "stop_reason": session.stop_reason
                if session.stop_reason is not None
                else "host_action_budget",
                "terminated": env.terminated,
                "truncated": env.truncated,
                "evaluation": evaluate(evaluation_input),
                "versions": {
                    "application": version("factored-worlds-doom-application"),
                    "pysmsl": version("pysmsl"),
                },
                "scope": "Teacher collection only; "
                "no discovered model or player-observation agent.",
            }
            (private / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    return report
