"""Native sequential and simultaneous multi-agent transitions."""

from contextlib import ExitStack
from importlib.metadata import version

import numpy as np

from factw.env.workers.farama.codecs import decode_action, describe_space, to_json
from factw.env.workers.farama.multiagent_config import configuration, create_environment
from factw.env.workers.farama.types import Observation, Transition


class Backend:
    def __init__(self, config: dict, suite: str = "pettingzoo"):
        self.suite = suite
        self.config, self.projection = configuration(config, suite)
        with ExitStack() as cleanup:
            self.env = create_environment(self.config)
            cleanup.callback(self.env.close)
            agents = self.env.possible_agents
            if any(type(agent) is not str for agent in agents) or len(set(agents)) != len(agents):
                raise ValueError("Native agent names must be unique strings")
            if suite == "momaland":
                if any(
                    self.env.reward_space(agent).shape != self.projection.weights.shape
                    for agent in agents
                ):
                    raise ValueError("Native reward spaces do not match objective_weights")
            cleanup.pop_all()
        self.started = False
        self.steps = 0
        self.total_reward = 0.0
        self.native_returns = {}
        self.final_status = {}
        self.last_infos = {}
        self.last_observations = {}
        self.native_rewards = {}
        self.terminated = self.truncated = False

    def reset(self, seed: int) -> Transition:
        self.steps = 0
        self.total_reward = 0.0
        self.native_returns = {}
        self.final_status = {}
        self.terminated = self.truncated = False
        self.started = True
        if self.config["api"] == "aec":
            self.env.reset(seed=seed)
            observation = self._aec_observation()
        else:
            observations, infos = self.env.reset(seed=seed)
            self.native_rewards = {}
            observation = self._parallel_observation(observations, {}, {}, {}, infos)
        return Transition(observation)

    def step(self, command: dict) -> Transition:
        if not self.started:
            raise RuntimeError("reset must precede step")
        if not self.env.agents:
            raise RuntimeError("episode has ended; reset before stepping")
        if not isinstance(command, dict):
            raise ValueError("command must be an object")
        previous_agents = set(self.env.agents)
        if self.config["api"] == "aec":
            self._step_aec(command)
            observation = self._aec_observation()
        else:
            actions = self._parallel_actions(command)
            values = self.env.step(actions)
            observation = self._parallel_observation(*values)
        self.steps += 1
        for agent in previous_agents - set(self.env.agents):
            if agent not in self.final_status:
                raise ValueError(f"Native agent {agent!r} disappeared without an ending flag")
        reward = self.projection.agents(self.native_rewards)
        self.total_reward += reward
        for agent, native in self.native_rewards.items():
            value = np.asarray(native, dtype=np.float64)
            if agent not in self.native_returns:
                self.native_returns[agent] = value.copy()
            else:
                self.native_returns[agent] += value
        if not self.env.agents:
            self.truncated = any(status["truncated"] for status in self.final_status.values())
            self.terminated = any(status["terminated"] for status in self.final_status.values())
        outcome = (
            "terminated_and_truncated"
            if self.terminated and self.truncated
            else "truncated"
            if self.truncated
            else "terminated"
            if self.terminated
            else "running"
        )
        return Transition(observation, reward, self.terminated, self.truncated, outcome)

    def _step_aec(self, command: dict):
        selected = self.env.agent_selection
        if command.keys() != {"agent", "action"} or command["agent"] != selected:
            raise ValueError(f"AEC command must name the currently selected agent {selected!r}")
        dead = self.env.terminations[selected] or self.env.truncations[selected]
        if dead:
            if command["action"] is not None:
                raise ValueError("A terminated/truncated AEC agent requires action: null")
            action = None
        else:
            action = decode_action(self.env.action_space(selected), command["action"])
        self.env.step(action)

    def _parallel_actions(self, command: dict) -> dict:
        if command.keys() != {"actions"} or not isinstance(command["actions"], dict):
            raise ValueError("Parallel command must contain an actions object")
        if command["actions"].keys() != set(self.env.agents):
            raise ValueError("Parallel actions must name exactly the currently live agents")
        return {
            agent: decode_action(self.env.action_space(agent), action)
            for agent, action in command["actions"].items()
        }

    def _status(self, terminations: dict, truncations: dict):
        if terminations.keys() != truncations.keys():
            raise ValueError("Native termination and truncation agent sets differ")
        for agent in terminations:
            if terminations[agent] or truncations[agent]:
                self.final_status[agent] = {
                    "terminated": bool(terminations[agent]),
                    "truncated": bool(truncations[agent]),
                }

    def _public_info(self, info: dict) -> dict:
        return {key: to_json(info[key]) for key in self.config["public_info_keys"] if key in info}

    def _aec_observation(self) -> Observation:
        self.native_rewards = dict(self.env.rewards)
        self.last_infos = dict(self.env.infos)
        self._status(self.env.terminations, self.env.truncations)
        selected = self.env.agent_selection if self.env.agents else None
        data = {
            "api": "aec",
            "agents": list(self.env.agents),
            "agent_selection": selected,
            "native_rewards": to_json(self.native_rewards),
            "terminations": to_json(self.env.terminations),
            "truncations": to_json(self.env.truncations),
            "final_agent_status": to_json(self.final_status),
        }
        self.last_observations = {}
        if selected is not None:
            observation, cumulative, terminated, truncated, info = self.env.last()
            self.last_observations = {selected: observation}
            data.update(
                {
                    "observation": to_json(observation),
                    "info": self._public_info(info),
                    "selected_agent_reward_since_last_turn": to_json(cumulative),
                    "selected_agent_terminated": bool(terminated),
                    "selected_agent_truncated": bool(truncated),
                }
            )
        return Observation(structured=data)

    def _parallel_observation(self, observations, rewards, terminations, truncations, infos):
        self.native_rewards = dict(rewards)
        self.last_infos = dict(infos)
        self.last_observations = dict(observations)
        self._status(terminations, truncations)
        return Observation(
            structured={
                "api": "parallel",
                "agents": list(self.env.agents),
                "observations": to_json(observations),
                "native_rewards": to_json(rewards),
                "terminations": to_json(terminations),
                "truncations": to_json(truncations),
                "infos": {agent: self._public_info(info) for agent, info in infos.items()},
                "final_agent_status": to_json(self.final_status),
            }
        )

    def metadata(self) -> dict:
        spaces = {
            agent: {
                "action": describe_space(self.env.action_space(agent)),
                "observation": describe_space(self.env.observation_space(agent)),
            }
            for agent in self.env.possible_agents
        }
        if self.suite == "momaland":
            for agent, data in spaces.items():
                data["reward"] = describe_space(self.env.reward_space(agent))
        return {
            "backend": self.suite,
            "configuration": self.config,
            "versions": {name: version(name) for name in {self.suite, "pettingzoo", "numpy"}},
            "api": self.config["api"],
            "spaces": spaces,
            "possible_agents": list(self.env.possible_agents),
            "snapshot": False,
            "replay": "seeded-actions",
            "observation_policy": self.config["observation_policy"],
            "observation_privacy": {
                "actor": self.config["observation_policy"],
                "centralized_actor": self.config["api"] == "parallel",
                "global_state": "not exposed",
                "render": "not exposed",
                "public_info_keys": self.config["public_info_keys"],
                "native_reward_maps": "public feedback for coordinator",
            },
            "reward_semantics": "explicit projection of instantaneous native reward map",
            "reward_projection": self.projection.config,
            "episode_end": (
                "all agents removed; independent any-agent termination and truncation flags"
            ),
        }

    def reference(self) -> dict:
        return {"step_count": self.steps, "native_infos": to_json(self.last_infos)}

    def evaluate(self) -> dict:
        return {
            "return": self.total_reward,
            "native_returns": to_json(self.native_returns),
            "terminated": self.terminated,
            "truncated": self.truncated,
            "final_agent_status": to_json(self.final_status),
        }

    def close(self):
        self.env.close()
