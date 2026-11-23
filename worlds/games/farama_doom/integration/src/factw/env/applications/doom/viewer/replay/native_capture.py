"""Read one human Doom demo in the owning ViZDoom worker environment."""

import argparse
import json
import shutil
from contextlib import closing
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory

import vizdoom
from factw.env.workers.doom.assets import provenance
from factw.env.workers.doom.play import CONTROLS, HUMAN_BUTTONS, STATISTICS
from PIL import Image

SCENARIOS = {
    "games.doom/retrieve-key-and-escape",
    "games.doom/activate-reactor-and-extract",
}


def configure(game, settings, source, config):
    game.load_config(str(config))
    bindings = settings / "doom.ini"
    bindings.write_text(
        "[Doom.Bindings]\n" + "".join(f"{key}={cmd}\n" for key, cmd in CONTROLS.items())
    )
    game.set_doom_config_path(str(bindings))
    if source["iwad_path"] is not None:
        game.set_doom_game_path(source["iwad_path"])
    game.set_doom_map(source["doom_map"])
    game.set_doom_skill(source["skill"])
    game.set_seed(source["seed"])
    available = set(game.get_available_buttons())
    for name in HUMAN_BUTTONS:
        button = getattr(vizdoom.Button, name)
        if button not in available:
            game.add_available_button(button)
    game.set_mode(vizdoom.Mode.PLAYER)
    game.set_window_visible(False)
    game.set_screen_resolution(getattr(vizdoom.ScreenResolution, source["resolution"]))
    game.set_screen_format(vizdoom.ScreenFormat.RGB24)
    game.set_render_hud(True)
    game.set_render_weapon(True)
    game.set_render_crosshair(True)
    game.set_render_all_frames(True)
    game.set_audio_buffer_enabled(False)
    game.set_automap_buffer_enabled(False)
    game.set_sound_enabled(False)
    game.add_game_args("+freelook 1")


def measure(game, channels, buttons, initial_tic):
    native_tic = int(game.get_episode_time())
    action = None
    if native_tic != initial_tic:
        action = {
            button: float(value)
            for button, value in zip(buttons, game.get_last_action(), strict=True)
            if value
        }
    return {
        "tic": native_tic - initial_tic,
        "native_tic": native_tic,
        "frame": None,
        "variables": {channel.name: float(game.get_game_variable(channel)) for channel in channels},
        "action": action,
        "return": float(game.get_total_reward()),
        "dead": bool(game.is_player_dead()),
        "native_timeout": bool(game.is_episode_timeout_reached()),
        "terminal": False,
    }


def render_frame(state, row, output, saved_frames):
    if state is None:
        return None
    if state.tic != row["native_tic"]:
        raise ValueError(f"RGB tic {state.tic} differs from telemetry tic {row['native_tic']}")
    rgb = state.screen_buffer
    identity = sha256(rgb.tobytes()).digest()
    if identity not in saved_frames:
        filename = f"frames/{row['tic']:05d}.png"
        Image.fromarray(rgb).save(output / filename, compress_level=3)
        saved_frames[identity] = filename
    return saved_frames[identity]


def verify_statistics(row, expected, name):
    for variable, value in expected.items():
        if row["variables"][variable] != value:
            raise ValueError(f"{name} replay {variable} differs from the recorded value")


def capture_frames(game, output, episode):
    channels = tuple(
        dict.fromkeys(
            (
                *game.get_available_game_variables(),
                *(getattr(vizdoom.GameVariable, name) for name in STATISTICS),
            )
        )
    )
    buttons = [button.name for button in game.get_available_buttons()]
    initial_tic = int(game.get_episode_time())
    frames, saved_frames = [], {}
    while not game.is_episode_finished():
        row = measure(game, channels, buttons, initial_tic)
        if row["tic"] != len(frames):
            raise ValueError(f"Replay skipped from relative tic {len(frames) - 1} to {row['tic']}")
        row["frame"] = render_frame(game.get_state(), row, output, saved_frames)
        frames.append(row)
        game.advance_action(1)
    if not frames:
        raise ValueError("The native replay produced no observations")
    verify_statistics(frames[0], episode["initial_statistics"], "Initial")

    boundary = measure(game, channels, buttons, initial_tic)
    terminal = bool(episode["native_finished"])
    terminal_tic = None
    if terminal and episode["observation_fresh"]:
        verify_statistics(boundary, episode["statistics"], "Final")
        for field in ("return", "dead", "native_timeout"):
            if boundary[field] != episode[field]:
                raise ValueError(f"Final replay {field} differs from the recorded value")
        if boundary["tic"] == len(frames):
            boundary["terminal"] = True
            frames.append(boundary)
            terminal_tic = boundary["tic"]
        elif boundary["native_tic"] == 0 and all(
            boundary[key] == frames[-1][key]
            for key in ("variables", "return", "dead", "native_timeout")
        ):
            frames[-1]["terminal"] = True
            terminal_tic = frames[-1]["tic"]
    return frames, {
        "stop_reason": episode["stop_reason"],
        "native_finished": terminal,
        "recorded_native_tic": episode["episode_tics"],
        "replay_native_tic": boundary["native_tic"],
        "terminal_tic": terminal_tic,
        "frame_available": terminal_tic is not None and frames[-1]["frame"] is not None,
        "return": boundary["return"],
        "dead": boundary["dead"],
        "native_timeout": boundary["native_timeout"],
        "variables": boundary["variables"],
    }


def capture(report_path, demo, config, output, episode_index=0):
    report_path = report_path.resolve(strict=True)
    demo = demo.resolve(strict=True)
    config = config.resolve(strict=True)
    report = json.loads(report_path.read_text())
    scenario = report["selection"]["scenario"]
    if report["mode"] != "human-async-spectator" or scenario not in SCENARIOS:
        raise ValueError("Select a human Key, Door, Exit or Reactor and Extract recording")
    if not 0 <= episode_index < len(report["episodes"]):
        raise ValueError("Choose an episode listed in the play report")
    episode = report["episodes"][episode_index]
    expected_demo = (report_path.parent / episode["demo"]).resolve(strict=True)
    if (
        not demo.is_relative_to(report_path.parent)
        or demo != expected_demo
        or not episode["demo_finalized"]
    ):
        raise ValueError("Select the finalized demo from the recorded run")
    data = demo.read_bytes()
    demo_sha256 = sha256(data).hexdigest()
    if len(data) != episode["demo_bytes"] or demo_sha256 != episode["demo_sha256"]:
        raise ValueError("Native demo differs from its recorded identity")
    if report["vizdoom_version"] != vizdoom.__version__:
        raise ValueError("The worker ViZDoom version differs from the recorded version")

    output.mkdir(parents=True, exist_ok=True)
    (output / "frames").mkdir()
    with TemporaryDirectory(prefix="fw-inspect-") as directory, closing(vizdoom.DoomGame()) as game:
        settings = Path(directory)
        native_demo = settings / "episode.lmp"
        shutil.copyfile(demo, native_demo)
        configure(game, settings, report["configuration"], config)
        game.init()
        assets = provenance(game, config)
        if assets != report["assets"]:
            raise ValueError("Replay assets differ from the recorded game")
        game.replay_episode(str(native_demo))
        frames, boundary = capture_frames(game, output, episode)
        result = {
            "schema": "factw.doom.human-captures/1",
            "scenario": scenario,
            "episode": episode_index,
            "ticrate": int(game.get_ticrate()),
            "demo_sha256": demo_sha256,
            "assets": assets,
            "vizdoom_version": vizdoom.__version__,
            "frames": frames,
            "boundary": boundary,
        }
    (output / "captures.json").write_text(
        json.dumps(result, separators=(",", ":"), allow_nan=False) + "\n"
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("report", "demo", "config", "output"):
        parser.add_argument(f"--{name}", required=True, type=Path)
    parser.add_argument("--episode", default=0, type=int)
    args = parser.parse_args()
    capture(args.report, args.demo, args.config, args.output, args.episode)


if __name__ == "__main__":
    main()
