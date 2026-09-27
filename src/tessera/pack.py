"""Sprite-sheet packing.

Rects are in image coordinates (origin top-left, y down). Exporters convert
to their engine's convention.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PIL import Image


@dataclass(frozen=True)
class Frame:
    name: str
    image: Image.Image


@dataclass(frozen=True)
class SpriteRect:
    """``border`` is an optional nine-slice border in pixels, given as
    (left, top, right, bottom) like the rect itself (top-left origin)."""
    name: str
    x: int
    y: int
    width: int
    height: int
    border: tuple[int, int, int, int] | None = None


@dataclass(frozen=True)
class Sheet:
    image: Image.Image
    sprites: tuple[SpriteRect, ...]


class PackError(Exception):
    pass


def load_frames(paths: list[Path]) -> list[Frame]:
    """One frame per file, named after the file stem, in the given order."""
    frames = []
    names = set()
    for path in paths:
        if path.stem in names:
            raise PackError(f"two frames named '{path.stem}'")
        names.add(path.stem)
        with Image.open(path) as image:
            frames.append(Frame(path.stem, image.convert("RGBA")))
    return frames


def slice_grid(image: Image.Image, cell_w: int, cell_h: int, prefix: str,
               skip_empty: bool = True) -> list[Frame]:
    """Cuts an image into cells, row by row, named ``prefix_0``, ``prefix_1``..."""
    if image.width % cell_w or image.height % cell_h:
        raise PackError(f"{image.width}x{image.height} is not a multiple of {cell_w}x{cell_h}")
    frames = []
    for y in range(0, image.height, cell_h):
        for x in range(0, image.width, cell_w):
            cell = image.crop((x, y, x + cell_w, y + cell_h))
            if skip_empty and cell.getbbox() is None:
                continue
            frames.append(Frame(f"{prefix}_{len(frames)}", cell))
    return frames


def pack(frames: list[Frame], padding: int = 0, columns: int | None = None,
         max_width: int = 2048) -> Sheet:
    """Packs frames. Equal-sized frames go on a grid in the given order (so
    animation frames stay readable); mixed sizes use shelf packing, tallest
    first."""
    if not frames:
        raise PackError("nothing to pack")
    names = [f.name for f in frames]
    if len(set(names)) != len(names):
        raise PackError("frame names must be unique")
    sizes = {f.image.size for f in frames}
    if len(sizes) == 1:
        return _pack_grid(frames, padding, columns, max_width)
    if columns is not None:
        raise PackError("columns only applies when all frames have the same size")
    return _pack_shelves(frames, padding, max_width)


def _pack_grid(frames, padding, columns, max_width) -> Sheet:
    w, h = frames[0].image.size
    fit = max(1, (max_width + padding) // (w + padding))
    if columns is None:
        columns = min(len(frames), fit)
    if columns * (w + padding) - padding > max_width:
        raise PackError(f"{columns} columns of {w}px do not fit in max_width {max_width}")
    rows = -(-len(frames) // columns)
    sheet = Image.new("RGBA", (columns * (w + padding) - padding, rows * (h + padding) - padding))
    rects = []
    for index, frame in enumerate(frames):
        x = (index % columns) * (w + padding)
        y = (index // columns) * (h + padding)
        sheet.paste(frame.image, (x, y))
        rects.append(SpriteRect(frame.name, x, y, w, h))
    return Sheet(sheet, tuple(rects))


def _pack_shelves(frames, padding, max_width) -> Sheet:
    order = sorted(frames, key=lambda f: (-f.image.height, -f.image.width, f.name))
    placements = []
    x = y = shelf_h = sheet_w = 0
    for frame in order:
        w, h = frame.image.size
        if w > max_width:
            raise PackError(f"'{frame.name}' is {w}px wide, more than max_width {max_width}")
        if x and x + w > max_width:
            x, y, shelf_h = 0, y + shelf_h + padding, 0
        placements.append((frame, x, y))
        sheet_w = max(sheet_w, x + w)
        shelf_h = max(shelf_h, h)
        x += w + padding
    sheet = Image.new("RGBA", (sheet_w, y + shelf_h))
    by_name = {}
    for frame, px, py in placements:
        sheet.paste(frame.image, (px, py))
        by_name[frame.name] = SpriteRect(frame.name, px, py, *frame.image.size)
    # Keep the caller's order in the metadata.
    return Sheet(sheet, tuple(by_name[f.name] for f in frames))
