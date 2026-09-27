"""Review images: nearest-neighbor upscales, tiled repeats, contact sheets and
animation strips. Previews are for looking at; they are never exported.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

from tessera.palette import Color

CHECKER_LIGHT = (204, 204, 204, 255)
CHECKER_DARK = (153, 153, 153, 255)


def upscale(image: Image.Image, scale: int) -> Image.Image:
    if scale < 1:
        raise ValueError(f"scale must be at least 1, got {scale}")
    image = image.convert("RGBA")
    return image.resize((image.width * scale, image.height * scale), Image.Resampling.NEAREST)


def backdrop(size: tuple[int, int], background: Color | None, cell: int = 8) -> Image.Image:
    """A solid background, or a checkerboard when ``background`` is None."""
    if background is not None:
        return Image.new("RGBA", size, background)
    image = Image.new("RGBA", size, CHECKER_LIGHT)
    draw = ImageDraw.Draw(image)
    for y in range(0, size[1], cell):
        for x in range(0, size[0], cell):
            if (x // cell + y // cell) % 2:
                draw.rectangle([x, y, x + cell - 1, y + cell - 1], fill=CHECKER_DARK)
    return image


def flatten(image: Image.Image, background: Color | None, cell: int = 8) -> Image.Image:
    base = backdrop(image.size, background, cell)
    base.alpha_composite(image.convert("RGBA"))
    return base


def tiled(image: Image.Image, repeat_x: int = 3, repeat_y: int = 3) -> Image.Image:
    """Repeats a tile so seams show up."""
    image = image.convert("RGBA")
    out = Image.new("RGBA", (image.width * repeat_x, image.height * repeat_y))
    for y in range(repeat_y):
        for x in range(repeat_x):
            out.paste(image, (x * image.width, y * image.height))
    return out


def draw_grid(image: Image.Image, step: int, color: Color) -> Image.Image:
    """Draws grid lines every ``step`` pixels (use on an upscaled image)."""
    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    for x in range(step, image.width, step):
        draw.line([(x, 0), (x, image.height - 1)], fill=color)
    for y in range(step, image.height, step):
        draw.line([(0, y), (image.width - 1, y)], fill=color)
    out = image.copy()
    out.alpha_composite(overlay)
    return out


def contact_sheet(images: list[Image.Image], columns: int | None = None,
                  gutter: int = 1) -> Image.Image:
    """Lays images out on a grid of equal cells (the largest image's size),
    each centered in its cell. Unscaled; upscale the result for review."""
    if not images:
        raise ValueError("contact sheet needs at least one image")
    cell_w = max(i.width for i in images)
    cell_h = max(i.height for i in images)
    columns = columns or max(1, round(len(images) ** 0.5))
    rows = -(-len(images) // columns)
    sheet = Image.new("RGBA", (columns * cell_w + (columns + 1) * gutter,
                               rows * cell_h + (rows + 1) * gutter), (0, 0, 0, 0))
    for index, image in enumerate(images):
        col, row = index % columns, index // columns
        x = gutter + col * (cell_w + gutter) + (cell_w - image.width) // 2
        y = gutter + row * (cell_h + gutter) + (cell_h - image.height) // 2
        sheet.paste(image.convert("RGBA"), (x, y))
    return sheet


def strip(frames: list[Image.Image], gutter: int = 1) -> Image.Image:
    """Animation frames side by side, in order."""
    return contact_sheet(frames, columns=len(frames), gutter=gutter)


def save_gif(frames: list[Image.Image], path: Path, scale: int, frame_ms: int,
             background: Color | None) -> None:
    """An animated preview; frames are flattened because GIF alpha is 1-bit."""
    size = (max(f.width for f in frames), max(f.height for f in frames))
    rendered = []
    for frame in frames:
        canvas = Image.new("RGBA", size, (0, 0, 0, 0))
        canvas.paste(frame.convert("RGBA"), (0, 0))
        rendered.append(flatten(upscale(canvas, scale), background, cell=scale * 2))
    rendered[0].save(path, save_all=True, append_images=rendered[1:], duration=frame_ms,
                     loop=0, disposal=2)
