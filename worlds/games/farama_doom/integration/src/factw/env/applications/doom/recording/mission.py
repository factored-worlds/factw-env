"""Record a declared State Language mission with bounded public transitions."""

import hashlib
import os
import shutil
from contextlib import ExitStack
from importlib.metadata import version
from pathlib import Path
from random import Random
from time import monotonic, sleep

from factw.env.core.recording import EpisodeWriter
from factw.env.core.recording.jsonio import read_json
from factw.env.external.collect import save
from factw.env.external.env import connect
from factw.env.worlds.doom.assets import (
    scenario_configuration,
    scenario_identity,
    validate_runtime,
)
from factw.env.worlds.doom.navigation_map import navigation_map_receipt

from ..evaluation import evaluate
from ..host.profile_inspection import selected_profile
from ..information.recording_view import RecordingView
from ..runtime.paced_environment import PacedEnvironment
from ..viewer import write_viewer
from ..viewer.buttons import ButtonWindow
from .buffered_media import Capture, Recorder
from .documents import write_documents


def record_mission(
    output,
    worker_command,
    *,
    seed=0,
    start=0,
    max_steps=500,
    max_skill_steps=80,
    visible=False,
    button_window=False,
    scenario_dir,
    session_type,
    mission,
    presentation=None,
    planner=None,
    information_profile="reference-assisted",
    startup_iwad=None,
    buffered_media=False,
    paced=False,
    real_time=False,
    archive_map=False,
):
    selection = selected_profile(mission, information_profile, planner=planner)
    if planner is not None:
        planner.validate(mission)
    for value, name in ((max_steps, "max_steps"), (max_skill_steps, "max_skill_steps")):
        if type(value) is not int or value < 1:
            raise ValueError(f"{name} must be a positive integer")
    if visible or os.environ.get("FACTW_DOOM_PLAYER_VIEW") == "1":
        presentation = {
            "render_hud": True,
            "render_weapon": True,
            "render_crosshair": True,
            **(presentation or {}),
        }
    if start is None:
        fixtures = read_json(Path(scenario_dir) / "manifest.json")["fixtures"]
        start = Random(seed).randrange(len(fixtures))
    config, manifest = scenario_configuration(
        scenario_dir, start=start, visible=visible, presentation=presentation
    )
    if startup_iwad is not None:
        path = Path(startup_iwad).resolve(strict=True)
        expected = manifest["runtime"]["iwad"]
        if not path.is_file() or path.name != expected["name"]:
            raise ValueError("Startup IWAD must name the declared scenario resource")
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected["sha256"]:
            raise ValueError("Startup IWAD hash differs from the scenario manifest")
        config["iwad_path"] = str(path)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    recorded_config = config
    map_metadata = {}
    if archive_map:
        directory = shutil.copytree(scenario_dir, output / "scenario_assets")
        cfg = directory / manifest["config_file"]
        config = {**config, "config_path": str(cfg.resolve())}
        recorded_config = {**config, "config_path": cfg.relative_to(output).as_posix()}
        map_metadata = {
            "scenario_manifest": navigation_map_receipt(directory),
            "domain": manifest["domain"],
        }
    document_hashes = write_documents(output, mission, planner=planner)
    private = output / "privileged"
    private.mkdir()
    save(private / "information_profile.json", selection)
    save(output / "configuration.json", recorded_config)
    save(output / "scenario.json", manifest)
    with ExitStack() as resources:
        buttons = resources.enter_context(ButtonWindow()) if button_window else None
        log = resources.enter_context((output / "worker.log").open("x"))
        capture = None
        transport_config = config
        if buffered_media or paced:
            if config.get("depth", False):
                raise ValueError("Buffered Doom recording supports RGB without depth")
            capture = Capture(resources, config.get("resolution", "RES_320X240"))
            transport_config = {**config, "recording_rgb_buffer": str(capture.path)}
        env = resources.enter_context(
            connect(worker_command, "vizdoom", transport_config, max_steps=max_steps, stderr=log)
        )
        resources.callback(env.close)
        validate_runtime(env.metadata, manifest)
        if paced:
            clock = resources.enter_context(PacedEnvironment(env, capture, max_steps=max_steps))
            session_options = {"apply_command": clock.apply}
        else:
            clock, session_options = None, {}
        recording = RecordingView(config, sensor_encodings=env.metadata.get("sensor_encodings", {}))
        save(private / "recording_rights.json", recording.describe())
        session = resources.enter_context(
            session_type(
                env if clock is None else clock,
                scene_spec=manifest["scene_spec"],
                max_skill_steps=max_skill_steps,
                planner=planner,
                information_profile=information_profile,
                **session_options,
            )
        )
        initial = recording.observation(session.reset(seed=seed))
        initial_inspection = session.inspect()
        if capture is not None:
            initial, initial_frame_status = capture.record(initial)
            initial_inspection["frame_status"] = initial_frame_status
        save(private / "initial-inspection.json", initial_inspection)
        writer = resources.enter_context(
            EpisodeWriter(
                output / "episode",
                initial,
                engine="benchmark-vizdoom-v1",
                engine_version=version("factored-worlds-external"),
                action_interface="benchmark-command-v1",
                seed=seed,
                task_id=mission,
                initial_terminated=env.terminated,
                schema_version="2.0",
                sensor_encodings=env.metadata.get("sensor_encodings", {}),
                **scenario_identity(mission),
            )
        )
        writer.manifest["benchmark"] = env.metadata
        writer.manifest["application"] = {
            "name": "doom-state-language-agent",
            "scenario": mission,
            **scenario_identity(mission),
            "versions": {
                "pysmsl": version("pysmsl"),
                "application": version("factored-worlds-doom-application"),
            },
            "smsl": document_hashes,
            "observation_profile": "reference-assisted",
            "information": session.boundary.describe(),
            "planner": None if planner is None else planner.describe(),
            "task_instruction": manifest["task_instruction"]
            if "task_instruction" in manifest
            else "Collect the blue key, open the locked door, and reach the exit.",
            "supplied_inputs": {
                "pose": ["POSITION_X", "POSITION_Y", "ANGLE"],
                "health": "HEALTH",
                "game_variables": config["public_game_variables"],
                "visible_labels": (
                    ["id", "name", "category", "bbox", "position", "angle"]
                    if config.get("public_labels", False)
                    else None
                ),
                "scenario_signals": manifest["telemetry"],
                "topology": manifest["scene_spec"],
            },
            "start": manifest["fixtures"][start],
            "scenario_assets": manifest["assets"],
            **map_metadata,
            "success_rule": manifest.get(
                "success_rule", "fresh native exit signal and task postcondition"
            ),
        }
        recorder = None
        if capture is not None:
            recorder = resources.enter_context(
                Recorder(writer, private, capture, initial_frame_status)
            )
        count = 0
        playback_start = monotonic()
        simulated_time = 0.0
        while (step := session.tick()) is not None:
            command = {"command": step.command}
            result = recording.transition(step.result)
            if recorder is None:
                writer.append(command, result)
            count += 1
            simulated_time += step.result.elapsed_seconds
            state = session.inspect(history=False)
            entry = {
                "trace": step.trace,
                "inspection": {
                    key: state[key]
                    for key in (
                        "facts",
                        "basis",
                        "plan",
                        "skill",
                        "stop_reason",
                        "last_outcome",
                        "episode_tics",
                        "estimate",
                    )
                },
            }
            if "fireballs" in state:
                entry["inspection"]["fireballs"] = state["fireballs"]
            if recorder is None:
                save(private / f"step-{count:06d}.json", entry)
            else:
                recorder.append(
                    count,
                    command,
                    result,
                    entry,
                    frame=None if clock is None else clock.frame,
                )
            if buttons is not None:
                buttons.show(
                    step.command,
                    skill=step.trace["skill"],
                    step=count,
                    tics=state["episode_tics"],
                    elapsed_seconds=step.result.elapsed_seconds,
                )
            if (
                (visible or real_time)
                and clock is None
                and (delay := simulated_time - (monotonic() - playback_start)) > 0
            ):
                try:
                    sleep(delay)
                except KeyboardInterrupt:
                    session.cancel_active("interrupted")
                    session.stop_reason = "interrupted"
                    break
        if clock is not None:
            save(output / "clock.json", clock.finish())
        if recorder is not None:
            recorder.finish()
            save(output / "media.json", recorder.summary())
        final = session.inspect()
        evaluation_input = session.boundary.evaluation_inputs()
        save(private / "evaluation_input.json", evaluation_input)
        evaluation = evaluate(evaluation_input)
        report = {
            "scenario": mission,
            **scenario_identity(mission),
            "start": start,
            "fixture": manifest["fixtures"][start],
            **map_metadata,
            "seed": seed,
            "success": evaluation["success"],
            "evaluation": evaluation,
            "symbolic_success": session.success,
            "success_rule": manifest.get(
                "success_rule", "fresh native exit signal and task postcondition"
            ),
            "steps": count,
            "terminated": env.terminated,
            "truncated": env.truncated,
            "facts": final["facts"],
            "resources": {
                key: final["estimate"]["measurements"].get(key)
                for key in ("HEALTH", "ARMOR", "AMMO2", "KILLCOUNT")
            },
            "stop_reason": final["stop_reason"],
            "last_outcome": final["last_outcome"],
            "upstream": env.evaluate(),
            "observation_profile": "reference-assisted",
            "information": session.boundary.describe(),
            "planner": None if planner is None else planner.describe(),
        }
        save(output / "report.json", report)
        save(private / "execution.json", final)
        (private / "world.json").write_text(session.world.to_json() + "\n")
    write_viewer(output)
    return report
