from dataclasses import dataclass
from random import Random

RGB = tuple[int, int, int]


@dataclass(frozen=True)
class RenderStyle:
    background: RGB = (245, 243, 235)
    disk_colors: tuple[RGB, ...] = ((145, 150, 160), (230, 185, 40), (65, 155, 95))
    peg_colors: tuple[RGB, ...] = ((125, 85, 55), (50, 100, 180), (180, 65, 55))
    offset: tuple[int, int] = (0, 0)

    def __post_init__(self):
        if not isinstance(self.disk_colors, tuple) or not isinstance(self.peg_colors, tuple):
            raise ValueError("Palettes must be immutable tuples")
        if len(self.disk_colors) < 3 or len(self.peg_colors) != 3:
            raise ValueError("Supply at least three disk colors and exactly three peg colors")
        colors = (self.background, *self.disk_colors, *self.peg_colors)
        if any(
            not isinstance(color, tuple)
            or len(color) != 3
            or any(type(value) is not int or not 0 <= value <= 255 for value in color)
            for color in colors
        ):
            raise ValueError("Colors must be RGB tuples with integer channels in 0..255")
        if (
            not isinstance(self.offset, tuple)
            or len(self.offset) != 2
            or any(type(value) is not int for value in self.offset)
        ):
            raise ValueError("offset must be a pair of integer pixels")


DEFAULT_STYLE = RenderStyle()


def sample_style(seed: int) -> RenderStyle:
    rng = Random(seed)

    def jitter(color: RGB, amount: int) -> RGB:
        return tuple(value + rng.randint(-amount, amount) for value in color)

    return RenderStyle(
        background=jitter(DEFAULT_STYLE.background, 5),
        disk_colors=tuple(jitter(color, 14) for color in DEFAULT_STYLE.disk_colors),
        peg_colors=tuple(jitter(color, 10) for color in DEFAULT_STYLE.peg_colors),
        offset=(rng.randint(-5, 5), rng.randint(-4, 4)),
    )
