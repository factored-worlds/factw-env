"""Launch native gameplay in the explicitly selected simulator environment."""

import hashlib
import json
import shutil
import signal
import subprocess
import sys
from contextlib import ExitStack, contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory

from factw.env.core.recording.jsonio import read_json

from .assets import SCENARIOS, scenario_configuration, scenario_directory, scenario_identity
from .navigation_map import build_navigation_map, navigation_map_receipt

MISSIONS = tuple(name for name in SCENARIOS if not name.endswith("/eliminate-single-target"))
BUNDLED = {
    "freedoom2": "Full Freedoom 2 levels: weapons, enemies, resources, secrets and exits.",
    "deathmatch": "Arena combat with weapon/resource collection and recurring monsters.",
    "deadly_corridor": "Fight through a defended corridor to reach its goal.",
    "health_gathering_supreme": "Explore a maze and collect health to survive hazards.",
    "my_way_home": "Find the goal through connected rooms and dead ends.",
    "defend_the_center": "Aim, manage ammunition and survive approaching monsters.",
    "basic": "Small aiming and shooting smoke scenario.",
}


def scenarios():
    return {"native_presets": BUNDLED, "scenarios": SCENARIOS}


def play(
    output,
    worker_python,
    *,
    scenario=None,
    native_preset=None,
    start=None,
    doom_map="MAP01",
    skill=3,
    seed=None,
    episodes=1,
    max_tics=None,
    sound=True,
    resolution="RES_800X600",
    iwad=None,
    visible=True,
    scenario_dir=None,
):
    if scenario is not None and native_preset is not None:
        raise ValueError("Choose an authored scenario or a native preset")
    if scenario is not None and scenario not in SCENARIOS:
        raise ValueError(f"Unknown Doom scenario: {scenario}")
    if scenario == "games.doom/eliminate-single-target":
        native_preset = "basic"
    if scenario is None and native_preset is None:
        native_preset = "freedoom2"
    selection = {
        "scenario": scenario,
        "native_preset": native_preset,
        "scenario_directory": None
        if scenario_dir is None
        else str(Path(scenario_dir).resolve(strict=True)),
    }
    generate = (
        scenario == "games.doom/retrieve-key-and-escape"
        and seed is not None
        and start is None
        and scenario_dir is None
    )
    start = 0 if start is None else start
    seed = 0 if seed is None else seed
    output = Path(output)
    with ExitStack() as resources:
        arguments = []
        expected = None
        if scenario in MISSIONS:
            directory = scenario_dir
            if directory is None:
                directory = resources.enter_context(scenario_directory(scenario))
            if generate:
                temporary = resources.enter_context(TemporaryDirectory(prefix="fw-doom-map-"))
                generated = Path(temporary) / "scenario_assets"
                build_navigation_map(directory, generated, seed)
                directory = generated
            config, manifest = scenario_configuration(directory, start=start)
            arguments.extend(["--config", config["config_path"]])
            doom_map = config["doom_map"]
            expected = {key: manifest["runtime"][key] for key in ("iwad", "engine_resources")}
            for name, key in (("configuration", "config_file"), ("scenario", "wad_file")):
                filename = manifest[key]
                expected[name] = {
                    "name": Path(filename).name,
                    "sha256": manifest["assets"][filename],
                }
        elif native_preset in BUNDLED:
            if start != 0 or scenario_dir is not None:
                raise ValueError("--start and --scenario-dir select authored mission fixtures")
            arguments.extend(["--scenario", native_preset])
        else:
            raise ValueError(f"Unknown native Doom preset: {native_preset}")
        arguments.extend(
            [
                "--map",
                doom_map,
                "--skill",
                str(skill),
                "--seed",
                str(seed),
                "--episodes",
                str(episodes),
                "--resolution",
                resolution,
            ]
        )
        if max_tics is not None:
            arguments.extend(["--max-tics", str(max_tics)])
        if iwad is not None:
            arguments.extend(["--iwad", str(Path(iwad).resolve(strict=True))])
        if not sound:
            arguments.append("--silent")
        if not visible:
            arguments.append("--headless")
        print(
            "Launching Doom. WASD: move; mouse: aim/fire; E: use; 1–7/wheel: weapons. "
            "Ctrl-C in this terminal finishes recording.",
            file=sys.stderr,
            flush=True,
        )
        report = _launch(output, worker_python, arguments, expected)
        report["selection"] = selection
        if scenario in MISSIONS:
            report.update(scenario_identity(scenario))
        if generate:
            saved = output / "scenario_assets"
            shutil.move(generated, saved)
            report["domain"] = manifest["domain"]
            report["scenario_manifest"] = navigation_map_receipt(saved)
            report["configuration"]["config_path"] = str(
                saved.relative_to(output) / manifest["config_file"]
            )
        pending = output / ".play-report.json"
        pending.write_text(json.dumps(report, indent=2) + "\n")
        pending.replace(output / "play-report.json")
        return report


@contextmanager
def recorded_mission_assets(source, report):
    """Resolve the map that supplied this recording's native observations."""
    selection = report["selection"]
    if "scenario_manifest" in report:
        directory = source / "scenario_assets"
        if report["scenario_manifest"] != navigation_map_receipt(directory):
            raise ValueError("Recorded Doom map manifest differs from its saved identity")
        yield directory
    elif selection.get("scenario_directory") is not None:
        yield Path(selection["scenario_directory"])
    else:
        with scenario_directory(selection["scenario"]) as directory:
            yield directory


def replay(source, output, worker_python, *, episode=0, sound=True, visible=True):
    source = Path(source).resolve(strict=True)
    record = read_json(source / "play-report.json")
    entries = record["episodes"]
    if type(episode) is not int or not 0 <= episode < len(entries):
        raise ValueError("episode must select a recorded native demo")
    entry = entries[episode]
    if not entry["demo_finalized"]:
        raise ValueError("The selected native demo was not finalized")
    demo = (source / entry["demo"]).resolve(strict=True)
    if not demo.is_relative_to(source):
        raise ValueError("Native demos must remain within their recorded run")
    data = demo.read_bytes()
    if len(data) != entry["demo_bytes"] or hashlib.sha256(data).hexdigest() != entry["demo_sha256"]:
        raise ValueError("Native demo differs from its recorded identity")
    config = record["configuration"]
    selection = record.get("selection")
    with ExitStack() as resources:
        arguments = []
        if selection is not None and selection["scenario"] in MISSIONS:
            directory = resources.enter_context(recorded_mission_assets(source, record))
            _, manifest = scenario_configuration(directory)
            arguments.extend(["--config", str(Path(directory) / manifest["config_file"])])
        elif selection is not None and selection["native_preset"] is not None:
            arguments.extend(["--scenario", selection["native_preset"]])
        else:
            arguments.extend(["--config", config["config_path"]])
        arguments.extend(
            [
                "--map",
                config["doom_map"],
                "--skill",
                str(config["skill"]),
                "--seed",
                str(config["seed"]),
                "--resolution",
                config["resolution"],
                "--replay",
                str(demo),
            ]
        )
        if config["iwad_path"] is not None:
            arguments.extend(["--iwad", config["iwad_path"]])
        if not sound:
            arguments.append("--silent")
        if not visible:
            arguments.append("--headless")
        return _launch(output, worker_python, arguments, record["assets"])


def _launch(output, worker_python, arguments, expected):
    output = Path(output).resolve()
    if output.exists():
        raise FileExistsError(output)
    runtime = Path(worker_python).absolute()
    runtime.stat()
    command = [
        str(runtime),
        "-m",
        "factw.env.workers.doom.play",
        "--output",
        str(output),
        *arguments,
    ]
    with TemporaryDirectory(prefix="fw-doom-assets-") as directory:
        if expected is not None:
            path = Path(directory) / "assets.json"
            path.write_text(json.dumps(expected, allow_nan=False))
            command.extend(["--expected-assets", str(path)])
        with subprocess.Popen(
            command, text=True, stdout=subprocess.PIPE, start_new_session=True
        ) as process:
            try:
                stdout, _ = process.communicate()
            except KeyboardInterrupt:
                process.send_signal(signal.SIGINT)
                stdout, _ = process.communicate()
    if output.is_dir():
        (output / "native-console.log").write_text(stdout)
    if process.returncode:
        raise subprocess.CalledProcessError(process.returncode, command, stdout)
    return read_json(output / "play-report.json")
