from contextlib import ExitStack
from importlib.metadata import version
from math import isfinite
from pathlib import Path
from tempfile import TemporaryDirectory

from factw.env.workers.farama.types import Observation, Transition

from .assets import provenance
from .options import OPTIONS, apply, labels, validate
from .recording_rgb import RecordingRgb


class Backend:
    def __init__(self, config):
        import vizdoom as vzd

        allowed = OPTIONS | {
            "scenario",
            "config_path",
            "doom_map",
            "frame_skip",
            "episode_timeout",
            "resolution",
            "public_game_variables",
            "reference_game_variables",
            "depth",
            "visible",
            "recording_rgb_buffer",
        }
        if unknown := config.keys() - allowed:
            raise ValueError(f"Unknown ViZDoom configuration: {sorted(unknown)}")
        if "scenario" in config and "config_path" in config:
            raise ValueError("Choose scenario or config_path")
        self.config = {
            "scenario": "basic",
            "frame_skip": 4,
            "episode_timeout": None,
            "resolution": "RES_320X240",
            "public_game_variables": [],
            "reference_game_variables": [],
            "depth": False,
            "visible": False,
            **config,
        }
        recording_buffer = self.config.pop("recording_rgb_buffer", None)
        if recording_buffer is not None and (
            type(recording_buffer) is not str
            or not recording_buffer
            or self.config["depth"] is not False
        ):
            raise ValueError("A Doom recording slot requires a path and RGB-only capture")
        validate(self.config)
        if type(self.config["frame_skip"]) is not int or self.config["frame_skip"] < 1:
            raise ValueError("frame_skip must be a positive integer")
        timeout = self.config["episode_timeout"]
        if timeout is not None and (type(timeout) is not int or timeout < 1):
            raise ValueError("episode_timeout must be a positive integer tic count")
        for key in ("depth", "visible"):
            if type(self.config[key]) is not bool:
                raise ValueError(f"{key} must be Boolean")
        self.variables = {}
        for key in ("public_game_variables", "reference_game_variables"):
            names = self.config[key]
            if type(names) is not list or any(
                type(name) is not str or name not in vzd.GameVariable.__members__ for name in names
            ):
                raise ValueError(f"{key} must list ViZDoom GameVariable names")
            self.variables[key] = {name: getattr(vzd.GameVariable, name) for name in names}
        if self.config["resolution"] not in vzd.ScreenResolution.__members__:
            raise ValueError("Unknown ViZDoom resolution")
        if "doom_map" in config and (type(config["doom_map"]) is not str or not config["doom_map"]):
            raise ValueError("doom_map must be a nonempty map name")
        if "config_path" in config:
            path = Path(config["config_path"]).expanduser().resolve(strict=True)
            self.config["scenario"] = None
            self.config["config_path"] = str(path)
        else:
            name = self.config["scenario"]
            if type(name) is not str or not name or Path(name).name != name:
                raise ValueError("scenario must name a bundled ViZDoom scenario")
            path = Path(vzd.scenarios_path) / f"{name}.cfg"
            if not path.is_file():
                raise ValueError(f"Unknown bundled scenario: {name}")
        with ExitStack() as resources:
            self._recording_rgb = (
                None if recording_buffer is None else RecordingRgb(recording_buffer, resources)
            )
            settings = resources.enter_context(TemporaryDirectory(prefix="fw-vizdoom-"))
            self.game = vzd.DoomGame()
            resources.callback(self.game.close)
            self.game.load_config(str(path))
            if "doom_map" in config:
                self.game.set_doom_map(config["doom_map"])
            self.game.set_doom_config_path(str(Path(settings) / "doom.ini"))
            self.game.set_window_visible(self.config["visible"])
            self.game.set_mode(vzd.Mode.PLAYER)
            self.game.set_screen_format(vzd.ScreenFormat.RGB24)
            self.game.set_screen_resolution(
                getattr(vzd.ScreenResolution, self.config["resolution"])
            )
            self.game.set_depth_buffer_enabled(self.config["depth"])
            apply(self.game, self.config)
            if timeout is not None:
                self.game.set_episode_timeout(timeout)
            self.game.init()
            self.asset_provenance = provenance(self.game, path)
            self._resources = resources.pop_all()
        self.buttons = list(self.game.get_available_buttons())
        self.initialized = False
        self.steps, self.total_reward = 0, 0.0
        self.episode_tics = 0
        self.terminated = self.truncated = False

    def _variables(self, key):
        return {
            name: float(self.game.get_game_variable(item))
            for name, item in self.variables[key].items()
        }

    def _observation(self):
        state = self.game.get_state()
        structured = {
            "episode_tics": self.episode_tics,
            "upstream_episode_tics": int(self.game.get_episode_time()),
            "sensor_available": state is not None,
            "game_variables": self._variables("public_game_variables"),
        }
        if self.config.get("public_labels", False):
            structured["labels"] = labels(state)
        if state is None:
            return Observation(structured=structured)
        structured["state_number"] = int(state.number)
        if self._recording_rgb is not None:
            self._recording_rgb.publish(self.episode_tics, state.screen_buffer)
            return Observation(structured=structured)
        depth_buffer = state.depth_buffer.copy() if self.config["depth"] else None
        return Observation(
            structured=structured,
            rgb=state.screen_buffer.copy(),
            depth_buffer=depth_buffer,
            depth_buffer_encoding="vizdoom-depth-u8-v1" if self.config["depth"] else None,
        )

    def reset(self, seed):
        self.game.set_seed(seed)
        self.game.new_episode()
        self.initialized = True
        self.steps, self.total_reward = 0, 0.0
        self.episode_tics = int(self.game.get_episode_time())
        self.terminated = self.truncated = False
        return Transition(self._observation())

    def step(self, command):
        if not self.initialized or self.terminated or self.truncated:
            raise RuntimeError("Reset before stepping an inactive episode")
        if command.keys() != {"buttons"} or not isinstance(command["buttons"], dict):
            raise ValueError("ViZDoom command must contain a buttons object")
        pressed = command["buttons"]
        names = {button.name for button in self.buttons}
        if pressed.keys() - names:
            raise ValueError("Command contains buttons unavailable in this scenario")
        values = []
        for button in self.buttons:
            value = pressed.get(button.name, 0)
            if type(value) not in (int, float, bool) or not isfinite(value):
                raise ValueError("Button values must be finite numbers")
            if button.name.endswith("_DELTA"):
                if abs(value) > self.game.get_button_max_value(button):
                    raise ValueError("Delta button exceeds scenario maximum")
            elif value not in (0, 1):
                raise ValueError("Binary buttons require zero or one")
            values.append(value)
        reward = 0.0
        advanced = 0
        for _ in range(self.config["frame_skip"]):
            reward += float(self.game.make_action(values, 1))
            advanced += 1
            if self.game.is_episode_finished():
                break
        self.episode_tics += advanced
        elapsed = advanced / 35.0
        self.steps += 1
        self.total_reward += reward
        finished = self.game.is_episode_finished()
        self.truncated = bool(finished and self.game.is_episode_timeout_reached())
        self.terminated = bool(finished and not self.truncated)
        outcome = "truncated" if self.truncated else "terminated" if self.terminated else "running"
        return Transition(
            self._observation(), reward, self.terminated, self.truncated, outcome, elapsed
        )

    def metadata(self):
        result = {
            "backend": "vizdoom",
            "versions": {"vizdoom": version("vizdoom")},
            "configuration": self.config,
            "assets": self.asset_provenance,
            "snapshot": False,
            "replay": "seeded-actions",
            "buttons": [
                {
                    "name": button.name,
                    "kind": "delta" if button.name.endswith("_DELTA") else "binary",
                    "maximum": float(self.game.get_button_max_value(button)),
                }
                for button in self.buttons
            ],
            "reward_semantics": "unmodified scenario reward accumulated over frame_skip",
            "success_semantics": "not inferred from reward or episode termination",
            "time_semantics": "single-tic advances / 35; monotonic across terminal map changes",
            "terminal_observation": "RGB/depth absent when upstream state is unavailable",
            "depth_semantics": "upstream uint8 depth buffer, not metric distance",
            "sensor_encodings": {"depth_buffer": "vizdoom-depth-u8-v1"}
            if self.config["depth"]
            else {},
        }
        if self.config.get("public_labels", False):
            result["label_semantics"] = (
                "Visible native object labels with category, bounding box and 3D pose; "
                "explicit simulator assistance, not RGB-only perception; null without a live frame"
            )
        return result

    def reference(self):
        return {
            "game_variables": self._variables("reference_game_variables"),
            "episode_tics": self.episode_tics,
            "upstream_episode_tics": int(self.game.get_episode_time()),
        }

    def evaluate(self):
        return {
            "return": self.total_reward,
            "steps": self.steps,
            "success": None,
            "terminated": self.terminated,
            "truncated": self.truncated,
        }

    def close(self):
        self._resources.close()
