"""Native keyboard/mouse play and demo playback in the owning ViZDoom runtime."""

import argparse
import hashlib
import json
import os
import shutil
from contextlib import ExitStack
from pathlib import Path
from tempfile import TemporaryDirectory
from time import monotonic, sleep

from .assets import provenance
from .live_capture import LiveCapture

CONTROLS = {
    "w": "+forward",
    "s": "+back",
    "a": "+moveleft",
    "d": "+moveright",
    "e": "+use",
    "space": "+use",
    "mouse1": "+attack",
    "shift": "+speed",
    "1": "slot 1",
    "2": "slot 2",
    "3": "slot 3",
    "4": "slot 4",
    "5": "slot 5",
    "6": "slot 6",
    "7": "slot 7",
    "mwheelup": "weapnext",
    "mwheeldown": "weapprev",
    "tab": "togglemap",
}
STATISTICS = (
    "HEALTH",
    "ARMOR",
    "SELECTED_WEAPON",
    "SELECTED_WEAPON_AMMO",
    "KILLCOUNT",
    "ITEMCOUNT",
    "SECRETCOUNT",
    "POSITION_X",
    "POSITION_Y",
    "ANGLE",
)
HUMAN_BUTTONS = (
    "ATTACK",
    "SPEED",
    "STRAFE",
    "USE",
    "MOVE_RIGHT",
    "MOVE_LEFT",
    "MOVE_BACKWARD",
    "MOVE_FORWARD",
    "TURN_RIGHT",
    "TURN_LEFT",
    "TURN_LEFT_RIGHT_DELTA",
    "LOOK_UP_DOWN_DELTA",
    *(f"SELECT_WEAPON{index}" for index in range(1, 8)),
    "SELECT_NEXT_WEAPON",
    "SELECT_PREV_WEAPON",
)


def statistics(game, vzd):
    return {
        name: float(game.get_game_variable(getattr(vzd.GameVariable, name))) for name in STATISTICS
    }


def observe_episode(game, vzd):
    return {
        "native_finished": bool(game.is_episode_finished()),
        "dead": bool(game.is_player_dead()),
        "native_timeout": bool(game.is_episode_timeout_reached()),
        "episode_tics": int(game.get_episode_time()),
        "return": float(game.get_total_reward()),
        "statistics": statistics(game, vzd),
        "observation_fresh": True,
    }


def finalize_demo(game, entry, path, destination):
    if game.is_episode_finished():
        game.close()
    else:
        game.send_game_command("stop")
        game.advance_action(1)
        if game.is_recording_episode():
            raise RuntimeError("Native demo recording did not stop after the flush tic")
    data = path.read_bytes()
    if not data:
        raise RuntimeError("Native demo finalization produced an empty file")
    destination.write_bytes(data)
    entry.update(
        demo_finalized=True, demo_bytes=len(data), demo_sha256=hashlib.sha256(data).hexdigest()
    )


def run(
    output,
    *,
    config_path=None,
    scenario="freedoom2",
    doom_map="MAP01",
    skill=3,
    seed=0,
    episodes=1,
    max_tics=None,
    sound=True,
    resolution="RES_800X600",
    iwad_path=None,
    replay=None,
    visible=True,
    expected_assets=None,
):
    import vizdoom as vzd

    if type(episodes) is not int or episodes < 1 or type(skill) is not int or not 1 <= skill <= 5:
        raise ValueError("episodes must be positive and skill must be between 1 and 5")
    if max_tics is not None and (type(max_tics) is not int or max_tics < 1):
        raise ValueError("max_tics must be a positive integer")
    if resolution not in vzd.ScreenResolution.__members__:
        raise ValueError("Unknown ViZDoom resolution")
    if replay is not None and episodes != 1:
        raise ValueError("Replay selects one recorded episode")
    embedded_x11 = os.environ.get("FACTW_DOOM_EMBEDDED_X11") == "1"
    if embedded_x11 and (replay is not None or not visible):
        raise ValueError("Embedded X11 selects visible human play")
    if config_path is None:
        if not scenario or Path(scenario).name != scenario:
            raise ValueError("scenario must name a bundled configuration")
        config_path = Path(vzd.scenarios_path) / f"{scenario}.cfg"
    config_path = Path(config_path).resolve(strict=True)
    replay = None if replay is None else Path(replay).resolve(strict=True)
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    report = {
        "mode": "native-demo-replay" if replay else "human-async-spectator",
        "configuration": {
            "config_path": str(config_path),
            "doom_map": doom_map,
            "skill": skill,
            "seed": seed,
            "sound": sound,
            "resolution": resolution,
            "visible": visible,
            "iwad_path": None if iwad_path is None else str(Path(iwad_path).resolve(strict=True)),
        },
        "controls": CONTROLS,
        "episodes": [],
        "completed": False,
        "observation_condition": "Native human keyboard/mouse input; no SMSL agent commands.",
    }
    with ExitStack() as resources:
        settings = resources.enter_context(TemporaryDirectory(prefix="fw-doom-play-"))
        native_demo = Path(settings) / "episode.lmp"
        # ViZDoom silently drops native commands longer than 128 bytes.
        if len(f'recordmap "{native_demo}" {doom_map}'.encode()) > 128:
            raise ValueError("Native demo commands require a shorter temporary directory path")
        if replay:
            shutil.copyfile(replay, native_demo)
        game = vzd.DoomGame()
        resources.callback(game.close)
        live_path = os.environ.get("FACTW_DOOM_LIVE_CAPTURE") if not replay else None
        live = LiveCapture(live_path) if live_path else None
        if live is not None:
            resources.callback(live.close)
        entry = None
        demo = None
        try:
            game.load_config(str(config_path))
            bindings = Path(settings) / "doom.ini"
            bindings.write_text(
                "[Doom.Bindings]\n"
                + "\n".join(f"{key}={command}" for key, command in CONTROLS.items())
                + "\n"
            )
            game.set_doom_config_path(str(bindings))
            if iwad_path is not None:
                game.set_doom_game_path(str(Path(iwad_path).resolve(strict=True)))
            game.set_doom_map(doom_map)
            game.set_doom_skill(skill)
            game.set_seed(seed)
            available = set(game.get_available_buttons())
            for name in HUMAN_BUTTONS:
                button = getattr(vzd.Button, name)
                if button not in available:
                    game.add_available_button(button)
            game.set_mode(vzd.Mode.PLAYER if replay else vzd.Mode.ASYNC_SPECTATOR)
            game.set_window_visible(visible)
            game.set_screen_resolution(getattr(vzd.ScreenResolution, resolution))
            if live is not None:
                game.set_screen_format(vzd.ScreenFormat.RGB24)
            game.set_render_hud(True)
            game.set_render_weapon(True)
            game.set_render_crosshair(True)
            game.set_render_all_frames(True)
            game.set_audio_buffer_enabled(False)
            game.set_automap_buffer_enabled(False)
            game.set_sound_enabled(sound)
            args = "+freelook 1"
            if embedded_x11:
                args += " +viz_window_hidden 1"
            game.add_game_args(args)
            game.init()
            report["assets"] = provenance(game, config_path)
            report["vizdoom_version"] = vzd.__version__
            report["available_buttons"] = [button.name for button in game.get_available_buttons()]
            if expected_assets is not None and report["assets"] != expected_assets:
                raise ValueError("Replay assets differ from the recorded game")
            for index in range(episodes):
                if not game.is_running():
                    game.init()
                demo = output / f"episode-{index:03d}.lmp"
                if replay:
                    game.replay_episode(str(native_demo))
                else:
                    game.new_episode(str(native_demo))
                initial_tic = int(game.get_episode_time())
                start = monotonic()
                entry = {
                    "index": index,
                    "demo": str(replay) if replay else demo.name,
                    "demo_finalized": bool(replay),
                    "stop_reason": None,
                    **observe_episode(game, vzd),
                }
                report["episodes"].append(entry)
                entry["initial_statistics"] = dict(entry["statistics"])
                if live is not None:
                    live.start_episode(game, index)
                    live.observe(game)
                stopped = "native_boundary"
                while not game.is_episode_finished():
                    if max_tics is not None and game.get_episode_time() - initial_tic >= max_tics:
                        stopped = "play_budget"
                        break
                    # SPECTATOR reads human input. It must never issue make_action().
                    game.advance_action(1)
                    if not (replay and game.is_episode_finished()):
                        entry.update(observe_episode(game, vzd))
                        if live is not None and not entry["native_finished"]:
                            live.observe(game)
                    if replay and visible:
                        due = (game.get_episode_time() - initial_tic) / game.get_ticrate()
                        remaining = due - (monotonic() - start)
                        if remaining > 0:
                            sleep(min(remaining, 0.05))
                if replay and game.is_episode_finished():
                    # The demo boundary resets native statistics; keep the last live sample.
                    entry.update(
                        native_finished=True,
                        dead=None,
                        native_timeout=None,
                        observation_fresh=False,
                        stop_reason="demo_complete",
                        native_boundary_tics=int(game.get_episode_time()),
                    )
                else:
                    entry.update(observe_episode(game, vzd), stop_reason=stopped)
                    if live is not None and entry["native_finished"]:
                        live.observe(game, terminal=True)
                if not replay:
                    finalize_demo(game, entry, native_demo, demo)
                entry = None
            report["completed"] = True
        except KeyboardInterrupt:
            report["stop_reason"] = "interrupted"
            if entry is not None:
                entry["stop_reason"] = "interrupted"
                if game.is_running():
                    entry.update(observe_episode(game, vzd))
                    if not replay:
                        finalize_demo(game, entry, native_demo, demo)
                else:
                    entry["observation_fresh"] = False
        except vzd.ViZDoomIsNotRunningException:
            report["stop_reason"] = "window_closed"
            if entry is not None:
                entry.update(stop_reason="window_closed", observation_fresh=False)
        finally:
            (output / "play-report.json").write_text(
                json.dumps(report, indent=2, allow_nan=False) + "\n"
            )
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--config", type=Path)
    source.add_argument("--scenario", default="freedoom2")
    parser.add_argument("--map", default="MAP01")
    parser.add_argument("--skill", type=int, choices=range(1, 6), default=3)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--episodes", type=int, default=1)
    parser.add_argument("--max-tics", type=int)
    parser.add_argument("--resolution", default="RES_800X600")
    parser.add_argument("--silent", action="store_true")
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--iwad", type=Path)
    parser.add_argument("--replay", type=Path)
    parser.add_argument("--expected-assets", type=Path)
    args = parser.parse_args()
    expected = (
        None if args.expected_assets is None else json.loads(args.expected_assets.read_text())
    )
    report = run(
        args.output,
        config_path=args.config,
        scenario=args.scenario,
        doom_map=args.map,
        skill=args.skill,
        seed=args.seed,
        episodes=args.episodes,
        max_tics=args.max_tics,
        sound=not args.silent,
        resolution=args.resolution,
        visible=not args.headless,
        iwad_path=args.iwad,
        replay=args.replay,
        expected_assets=expected,
    )
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
