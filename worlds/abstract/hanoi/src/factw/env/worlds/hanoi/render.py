from colorsys import hsv_to_rgb

import numpy as np
from factw.env.worlds.hanoi.style import DEFAULT_STYLE, RenderStyle
from PIL import Image, ImageDraw


def render(pegs: tuple[int, ...], style: RenderStyle = DEFAULT_STYLE) -> np.ndarray:
    image = Image.new("RGB", (384, 256), style.background)
    draw = ImageDraw.Draw(image)
    centers = tuple(center + style.offset[0] for center in (64, 192, 320))
    base = 228 + style.offset[1]
    thickness = min(24, 176 / len(pegs))
    for center, color in zip(centers, style.peg_colors, strict=True):
        draw.rounded_rectangle(
            (center - 5, 36 + style.offset[1], center + 5, base), radius=4, fill=color
        )
        draw.rounded_rectangle((center - 56, base, center + 56, base + 10), radius=3, fill=color)
    heights = [0, 0, 0]
    colors = style.disk_colors
    for disk in reversed(range(len(pegs))):
        peg = pegs[disk]
        center = centers[peg]
        half_width = 17 + 35 * (disk + 1) / len(pegs)
        bottom = base - heights[peg] * thickness - 2
        color = (
            colors[disk]
            if disk < len(colors)
            else tuple(round(255 * channel) for channel in hsv_to_rgb(disk * 0.618 % 1, 0.55, 0.8))
        )
        draw.rounded_rectangle(
            (
                center - half_width,
                bottom - thickness + min(3, thickness / 5),
                center + half_width,
                bottom,
            ),
            radius=min(5, thickness / 4),
            fill=color,
            outline=(55, 55, 55),
            width=1,
        )
        heights[peg] += 1
    return np.array(image, dtype=np.uint8, copy=True)
