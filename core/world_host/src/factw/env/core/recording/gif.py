import argparse
import math
from contextlib import ExitStack
from pathlib import Path

from factw.env.core.recording.reader import Episode
from PIL import Image


def render_gif(episode: str | Path, output: str | Path, *, stride: int = 1, fps: float = 5):
    if type(stride) is not int or stride < 1:
        raise ValueError("Stride must be a positive integer")
    if not math.isfinite(fps) or fps <= 0:
        raise ValueError("FPS must be finite and positive")
    recorded = Episode(episode)

    def observations():
        yield recorded.initial_observation()
        for transition in recorded.transitions():
            yield transition.result.observation

    with ExitStack() as resources:

        def frame(rgb):
            image = Image.fromarray(rgb)
            resources.callback(image.close)
            return image

        frames = []
        available = 0
        last_rgb = None
        for observation in observations():
            rgb = getattr(observation, "rgb", None)
            if rgb is None:
                continue
            if available % stride == 0:
                frames.append(frame(rgb))
            last_rgb = rgb
            available += 1
        if available == 0:
            raise ValueError("Episode contains no RGB observations to render")
        if (available - 1) % stride:
            frames.append(frame(last_rgb))
        frames[0].save(
            output,
            format="GIF",
            save_all=True,
            append_images=frames[1:],
            duration=max(1, round(1000 / fps)),
            loop=0,
        )


def main(argv=None):
    parser = argparse.ArgumentParser(description="Render a recorded episode as an animated GIF")
    parser.add_argument("episode", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--stride", type=int, default=1, help="Keep every Nth available RGB frame")
    parser.add_argument("--fps", type=float, default=5)
    args = parser.parse_args(argv)
    if args.stride < 1 or not math.isfinite(args.fps) or args.fps <= 0:
        parser.error("stride must be positive; fps must be finite and positive")
    render_gif(args.episode, args.output, stride=args.stride, fps=args.fps)


if __name__ == "__main__":
    main()
