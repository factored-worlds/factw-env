from contextlib import ExitStack
from importlib.metadata import version
from pathlib import Path
from time import monotonic, sleep

from factw.env.core.recording import EpisodeWriter
from factw.env.external.collect import save
from factw.env.external.env import connect
from factw.env.worlds.doom.assets import presentation_options, scenario_identity

from ...evaluation import evaluate
from ...host.profile_inspection import selected_profile
from ...information.privileged_state import BASIC
from ...information.recording_view import RecordingView
from ...providers.symbolic.single_target_native_pose import SweepPolicy
from ...recording.documents import write_documents
from ...viewer.buttons import ButtonWindow
from .session import COMMANDS, DoomSession


def run(
    output,
    worker_command,
    *,
    seed=0,
    max_steps=150,
    visible=False,
    button_window=False,
    presentation=None,
    information_profile="reference-assisted",
):
    selection = selected_profile(BASIC, information_profile)
    presentation = presentation_options(presentation)
    if type(max_steps) is not int or max_steps < 1:
        raise ValueError("max_steps must be a positive integer")
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    scenario = BASIC
    document_hashes = write_documents(output, scenario)
    private = output / "privileged"
    private.mkdir()
    save(private / "information_profile.json", selection)
    config = {
        "scenario": "basic",
        "frame_skip": 4,
        "episode_timeout": 600,
        "public_game_variables": ["POSITION_Y", "AMMO2", "HEALTH", "KILLCOUNT"],
        "visible": visible,
    }
    config.update(presentation)
    save(output / "configuration.json", config)
    with ExitStack() as resources:
        buttons = resources.enter_context(ButtonWindow()) if button_window else None
        log = resources.enter_context((output / "worker.log").open("x"))
        env = resources.enter_context(
            connect(worker_command, "vizdoom", config, max_steps=max_steps, stderr=log)
        )
        session = resources.enter_context(DoomSession(env, information_profile=information_profile))
        recording = RecordingView(config, sensor_encodings=env.metadata.get("sensor_encodings", {}))
        save(private / "recording_rights.json", recording.describe())
        initial = session.reset(seed=seed)
        policy = SweepPolicy()
        trace = []
        writer = resources.enter_context(
            EpisodeWriter(
                output / "episode",
                recording.observation(initial),
                engine="benchmark-vizdoom-v1",
                engine_version=version("factored-worlds-external"),
                action_interface="benchmark-command-v1",
                seed=seed,
                task_id=scenario,
                initial_terminated=env.terminated,
                schema_version="2.0",
                sensor_encodings=env.metadata.get("sensor_encodings", {}),
                **scenario_identity(scenario),
            )
        )
        writer.manifest["benchmark"] = env.metadata
        writer.manifest["application"] = {
            "name": "doom-state-language-agent",
            "scenario": scenario,
            **scenario_identity(scenario),
            "smsl": document_hashes,
            "observation_profile": "reference-assisted",
            "information": session.boundary.describe(),
            "success_rule": "fresh Basic KILLCOUNT >= 1",
        }
        playback_start = monotonic()
        simulated_time = 0.0
        interrupted = False
        while True:
            view = session.policy_inputs()
            action = policy.choose(view)
            if action is None:
                break
            decision = session.propose_policy_action(action, view["provenance"])
            before = session.facts()
            result = session.step(decision)
            writer.append({"command": COMMANDS[decision.action]}, recording.transition(result))
            simulated_time += result.elapsed_seconds
            entry = {
                "basis": decision.basis,
                "capture_id": view["provenance"]["capture_id"],
                "access_sha256": view["provenance"]["access_sha256"],
                "action": decision.action,
                "facts_before": before,
                "facts_after": session.facts(),
                "episode_tics": session.telemetry.tics,
                "outcome": result.outcome,
            }
            trace.append(entry)
            save(private / f"step-{len(trace):06d}.json", entry)
            if buttons is not None:
                buttons.show(
                    COMMANDS[decision.action],
                    skill=decision.action,
                    step=len(trace),
                    tics=session.telemetry.tics,
                    elapsed_seconds=result.elapsed_seconds,
                )
            if visible and (delay := simulated_time - (monotonic() - playback_start)) > 0:
                try:
                    sleep(delay)
                except KeyboardInterrupt:
                    interrupted = True
                    break
        facts = session.facts()
        evaluation_input = session.boundary.evaluation_inputs()
        save(private / "evaluation_input.json", evaluation_input)
        evaluation = evaluate(evaluation_input)
        report = {
            "scenario": scenario,
            **scenario_identity(scenario),
            "success": evaluation["success"],
            "evaluation": evaluation,
            "symbolic_success": facts["won"],
            "success_rule": "Basic KILLCOUNT >= 1",
            "steps": len(trace),
            "episode_tics": session.telemetry.tics,
            "terminated": env.terminated,
            "truncated": env.truncated,
            "facts": facts,
            "upstream": env.evaluate(),
            "observation_profile": "reference-assisted",
            "information": session.boundary.describe(),
            "stop_reason": (
                "interrupted"
                if interrupted
                else "observed_kill"
                if facts["won"]
                else "episode_boundary"
                if not facts["active"]
                else "dead"
                if not facts["alive"]
                else "ammunition_exhausted"
            ),
        }
        save(output / "report.json", report)
        save(private / "execution.json", session.execution.inspect())
        (private / "world.json").write_text(session.world.to_json() + "\n")
    return report
