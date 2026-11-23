"""Show Doom and its State Language facts in one desktop window."""

import os
import signal
import subprocess
import sys
from contextlib import ExitStack
from pathlib import Path
from uuid import uuid4

from .records import LiveRecords, completed_json
from .window import LiveWindow


def follow(
    command,
    records,
    completion,
    *,
    human=False,
    environment=None,
    game_resolution=None,
):
    with ExitStack() as resources:
        window = LiveWindow(
            on_close=lambda: window.root.quit(), human=human, game_resolution=game_resolution
        )
        root = window.root
        resources.callback(root.destroy)
        window.status("Starting Doom…")
        root.update_idletasks()
        game = None
        if human:
            from .native_window import NativeWindow

            window_class = f"factw-doom-{uuid4().hex}"
            panel = window.game_panel
            game = resources.enter_context(
                NativeWindow(root.winfo_screen(), panel.winfo_id(), window_class)
            )
            environment = {
                **(os.environ if environment is None else environment),
                "FACTW_DOOM_EMBEDDED_X11": "1",
                "SDL_VIDEODRIVER": "x11",
                "SDL_VIDEO_X11_WMCLASS": window_class,
                "SDL_MOUSE_RELATIVE_MODE_WARP": "0",
            }
            if game_resolution is None:
                command = [*command, "--resolution", window.game_resolution]
        return _follow(window, game, command, records, completion, environment)


def _follow(window, game, command, records, completion, environment):
    root = window.root
    human = game is not None
    latest_change = None
    episode = None
    interrupted = None
    window_error = None
    finished = False

    with subprocess.Popen(command, start_new_session=True, env=environment) as player:

        def stop(signum, _frame):
            nonlocal interrupted
            if interrupted is None:
                interrupted = signum
                player.send_signal(signal.SIGINT if human else signum)

        def close_window():
            if human and player.poll() is None:
                stop(signal.SIGINT, None)
            else:
                root.quit()

        def show_error(_kind, error, traceback):
            nonlocal window_error
            window_error = error.with_traceback(traceback)
            if human and player.poll() is None:
                stop(signal.SIGINT, None)
            root.quit()

        def refresh():
            nonlocal episode, latest_change, finished
            code = player.poll()
            if interrupted is not None:
                if not human or code is not None:
                    root.quit()
                else:
                    window.status("Saving recording…")
                    root.after(35, refresh)
                return
            if not finished:
                if human:
                    panel = window.game_panel
                    available = code is None and game.poll(
                        panel.winfo_width(), panel.winfo_height()
                    )
                    window.set_native_active(available)
                newest = None
                newest_frame = None
                for _ in range(128):
                    step = records.poll()
                    if step is None:
                        break
                    if step.episode != episode:
                        episode = step.episode
                        latest_change, newest_frame = None, None
                    newest = step
                    if any(step.changes.values()):
                        latest_change = step
                    if step.rgb is not None:
                        newest_frame = step, latest_change
                if newest is not None:
                    if newest.rgb is None and newest_frame is not None:
                        window.render(*newest_frame)
                    window.render(newest, latest_change)
                if code is not None and step is None:
                    outcome = completion() if code == 0 else f"Doom exited with status {code}"
                    window.finish(outcome)
                    finished = True
            root.after(150 if finished else 35, refresh)

        root.protocol("WM_DELETE_WINDOW", close_window)
        root.report_callback_exception = show_error
        handlers = {
            number: signal.signal(number, stop) for number in (signal.SIGINT, signal.SIGTERM)
        }
        try:
            root.after(0, refresh)
            root.mainloop()
            if not human:
                root.withdraw()
            if player.poll() is None:
                if human:
                    stop(signal.SIGINT, None)
                elif interrupted is None:
                    print("Doom viewer closed. Doom is still recording.", flush=True)
            code = player.wait()
        finally:
            for number, handler in handlers.items():
                signal.signal(number, handler)
    if window_error is not None:
        raise window_error
    return code if code >= 0 else 128 - code


def run(output, command):
    records = LiveRecords(output)

    def completion():
        report = completed_json(output / "report.json")
        if report is None or report["steps"] != records.next_index - 1:
            raise ValueError("The final Doom report and displayed steps disagree")
        return "Mission complete" if report["success"] else "Mission ended"

    print("Doom agent: live frames and SMSL facts", flush=True)
    return follow(
        command,
        records,
        completion,
        environment={**os.environ, "FACTW_DOOM_PLAYER_VIEW": "1"},
    )


if __name__ == "__main__":
    raise SystemExit(run(Path(sys.argv[1]), sys.argv[2:]))
