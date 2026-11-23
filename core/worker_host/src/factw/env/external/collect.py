import json
from contextlib import ExitStack
from pathlib import Path

from factw.env.core.recording import EpisodeWriter
from factw.env.external import __version__
from factw.env.external.env import connect


def save(path: Path, value):
    with path.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(value, indent=2, allow_nan=False, ensure_ascii=False) + "\n")


def collect(
    output,
    command,
    backend,
    parameters,
    actions,
    *,
    seed=0,
    max_steps=1000,
    timeout=120.0,
    references=False,
    evaluate=False,
    state_language=False,
    task_id=None,
):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    with ExitStack() as resources:
        log = resources.enter_context((output / "worker.log").open("x"))
        env = resources.enter_context(
            connect(command, backend, parameters, max_steps=max_steps, timeout=timeout, stderr=log)
        )
        session = None
        if state_language:
            from factw.env.external.state_language import StateLanguageSession

            session = resources.enter_context(StateLanguageSession(env))
        initial = (env if session is None else session).reset(seed=seed)
        if env.truncated:
            raise ValueError("An upstream reset cannot start an already truncated recording")
        private = output / "privileged"
        private.mkdir()
        if references:
            save(private / "reference-000000.json", env.reference())
        with EpisodeWriter(
            output / "episode",
            initial,
            engine_version=__version__,
            engine=f"benchmark-{backend}-v1",
            action_interface="benchmark-command-v1",
            seed=seed,
            task_id=backend if task_id is None else task_id,
            initial_terminated=env.terminated,
            schema_version="2.0",
            sensor_encodings=env.metadata.get("sensor_encodings", {}),
        ) as writer:
            writer.manifest["benchmark"] = env.metadata
            for action in actions:
                observed = (
                    env.step(action)
                    if session is None
                    else session.step(action, basis=session.basis)
                )
                writer.append({"command": action}, observed)
                if references:
                    save(private / f"reference-{env.steps:06d}.json", env.reference())
            if evaluate:
                save(private / "evaluation.json", env.evaluate())
        if session is not None:
            save(output / "state-language.json", session.inspect())
    return output / "episode"
