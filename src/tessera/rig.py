"""Part-based character rigs.

A character is drawn once as parts (head, hair, torso, arms, legs, clothing,
held tools) and posed per frame from data. Parts are painted in *slots* and
*levels* instead of colors: a slot is a recolorable role ("skin", "hair",
"top"), a level is a shade from 0 (darkest) to ``levels - 1`` (brightest).
A ``Look`` maps each slot to a ramp of colors, so the same rig renders any
skin, hair or clothing colors (palette swap) without touching the art.

Directions: ``down``, ``up``, ``right`` and ``left``. A rig may leave ``left``
out; it is then the mirror of ``right``.

Rendering order per frame: parts are stamped in pose order (later parts on
top) into a slot/level buffer, the buffer is mirrored if needed, then the
outline pass runs. A pixel is outlined when it borders transparency or a part
drawn *earlier* (below it), so each part gets one outline where it overlaps
another, never two. Outline modes (the project's ``shading.outline``):

- ``none``: no pass.
- ``dark``: border pixels take level 0.
- ``selective``: level 0 on the bottom and right, one level down on the top
  and left (light from the top-left).

Coordinates are image coordinates (x right, y down), relative to the frame's
top-left corner.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from PIL import Image

from tessera.config import ProjectConfig
from tessera.exporters import ExportAsset, ExportError, create_exporter
from tessera.pack import Frame, pack
from tessera.palette import Color, validate_image

DIRECTIONS = ("down", "up", "right", "left")
OUTLINES = ("none", "dark", "selective")
TRANSPARENT = "."

Pixel = tuple[str, int]  # (slot, level)


class RigError(Exception):
    pass


@dataclass(frozen=True)
class Part:
    """A small slot/level image. ``outline`` False keeps the part out of the
    outline pass (for details such as eyes drawn on top of another part)."""
    name: str
    width: int
    height: int
    pixels: Mapping[tuple[int, int], Pixel]
    outline: bool = True

    @staticmethod
    def from_rows(name: str, rows: Sequence[str], legend: Mapping[str, Pixel],
                  outline: bool = True) -> "Part":
        """Builds a part from text rows, one character per pixel. ``.`` and
        spaces are transparent; every other character must be in ``legend``."""
        rows = [r.rstrip("\n") for r in rows]
        if not rows:
            raise RigError(f"part '{name}' has no rows")
        width = max(len(r) for r in rows)
        pixels = {}
        for y, row in enumerate(rows):
            for x, ch in enumerate(row):
                if ch in (TRANSPARENT, " "):
                    continue
                if ch not in legend:
                    raise RigError(f"part '{name}' row {y}: '{ch}' is not in the legend")
                pixels[(x, y)] = legend[ch]
        return Part(name, width, len(rows), pixels, outline)

    def mirrored(self, name: str | None = None) -> "Part":
        return Part(name or self.name, self.width, self.height,
                    {(self.width - 1 - x, y): p for (x, y), p in self.pixels.items()},
                    self.outline)

    def slots(self) -> set[str]:
        return {slot for slot, _ in self.pixels.values()}


@dataclass(frozen=True)
class Place:
    """One part in a pose: its top-left corner in the frame."""
    part: str
    x: int
    y: int


@dataclass(frozen=True)
class Animation:
    name: str
    direction: str
    frames: tuple[tuple[Place, ...], ...]
    fps: float
    loop: bool = True

    def __post_init__(self):
        if self.direction not in DIRECTIONS:
            raise RigError(f"animation '{self.name}': unknown direction '{self.direction}'")
        if not self.frames:
            raise RigError(f"animation '{self.name}_{self.direction}' has no frames")
        if self.fps <= 0:
            raise RigError(f"animation '{self.name}_{self.direction}': fps must be positive")

    @property
    def key(self) -> str:
        return f"{self.name}_{self.direction}"


@dataclass(frozen=True)
class Look:
    """Slot -> ramp (darkest first). Every ramp has the rig's level count."""
    name: str
    ramps: Mapping[str, Sequence[Color]]

    def color(self, slot: str, level: int) -> Color:
        ramp = self.ramps[slot]
        return ramp[max(0, min(len(ramp) - 1, level))]


@dataclass
class Rig:
    name: str
    frame_size: tuple[int, int]
    levels: int
    parts: dict[str, Part] = field(default_factory=dict)
    animations: dict[str, Animation] = field(default_factory=dict)

    def add_part(self, part: Part) -> Part:
        if part.name in self.parts:
            raise RigError(f"two parts named '{part.name}'")
        for slot, level in part.pixels.values():
            if not 0 <= level < self.levels:
                raise RigError(f"part '{part.name}': level {level} outside 0..{self.levels - 1}")
        self.parts[part.name] = part
        return part

    def add_animation(self, name: str, direction: str, frames: Iterable[Iterable[Place]],
                      fps: float, loop: bool = True) -> Animation:
        anim = Animation(name, direction, tuple(tuple(f) for f in frames), fps, loop)
        if anim.key in self.animations:
            raise RigError(f"two animations named '{anim.key}'")
        for frame in anim.frames:
            for place in frame:
                if place.part not in self.parts:
                    raise RigError(f"animation '{anim.key}' uses unknown part '{place.part}'")
        self.animations[anim.key] = anim
        return anim

    def mirror_left(self) -> None:
        """Adds a ``left`` animation for every ``right`` one that has none;
        left frames are rendered mirrored (see ``render``)."""
        for anim in list(self.animations.values()):
            if anim.direction == "right" and f"{anim.name}_left" not in self.animations:
                self.animations[f"{anim.name}_left"] = Animation(
                    anim.name, "left", anim.frames, anim.fps, anim.loop)

    def is_mirrored(self, anim: Animation) -> bool:
        return anim.direction == "left" and any(
            a.frames is anim.frames for a in self.animations.values() if a.direction == "right")

    def slots(self) -> set[str]:
        return set().union(*(p.slots() for p in self.parts.values())) if self.parts else set()

    # Rendering --------------------------------------------------------------

    def compose(self, places: Sequence[Place], mirror: bool = False) -> dict[tuple[int, int], tuple[str, int, int, bool]]:
        """Stamps parts into a buffer: (x, y) -> (slot, level, depth, outline)."""
        width, height = self.frame_size
        buffer: dict[tuple[int, int], tuple[str, int, int, bool]] = {}
        for depth, place in enumerate(places):
            part = self.parts[place.part]
            for (px, py), (slot, level) in part.pixels.items():
                x, y = place.x + px, place.y + py
                if 0 <= x < width and 0 <= y < height:
                    buffer[(x, y)] = (slot, level, depth, part.outline)
        if mirror:
            buffer = {(width - 1 - x, y): v for (x, y), v in buffer.items()}
        return buffer

    def outline(self, buffer, mode: str) -> dict[tuple[int, int], Pixel]:
        if mode not in OUTLINES:
            raise RigError(f"outline must be one of {', '.join(OUTLINES)}")
        result = {}
        for (x, y), (slot, level, depth, outlined) in buffer.items():
            if mode == "none" or not outlined:
                result[(x, y)] = (slot, level)
                continue
            sides = []
            for dx, dy, side in ((1, 0, "E"), (-1, 0, "W"), (0, 1, "S"), (0, -1, "N")):
                other = buffer.get((x + dx, y + dy))
                if other is None or (other[2] < depth and other[3]):
                    sides.append(side)
            if not sides:
                result[(x, y)] = (slot, level)
            elif mode == "selective" and all(s in ("N", "W") for s in sides):
                result[(x, y)] = (slot, max(0, level - 1))
            else:
                result[(x, y)] = (slot, 0)
        return result

    def render_pixels(self, anim: Animation, index: int, outline: str) -> dict[tuple[int, int], Pixel]:
        return self.outline(self.compose(anim.frames[index], self.is_mirrored(anim)), outline)

    def render(self, anim: Animation, index: int, look: Look, outline: str) -> Image.Image:
        missing = self.slots() - set(look.ramps)
        if missing:
            raise RigError(f"look '{look.name}' has no ramp for {', '.join(sorted(missing))}")
        image = Image.new("RGBA", self.frame_size, (0, 0, 0, 0))
        px = image.load()
        for (x, y), (slot, level) in self.render_pixels(anim, index, outline).items():
            px[x, y] = look.color(slot, level)
        return image

    def frame_name(self, anim: Animation, index: int) -> str:
        return f"{self.name}_{anim.key}_{index}"

    def frames(self, look: Look, outline: str, prefix: str | None = None) -> list[Frame]:
        """Every frame of every animation, named ``<prefix>_<anim>_<dir>_<i>``
        (prefix defaults to the rig name). Names are permanent once a game
        references them."""
        prefix = prefix or self.name
        out = []
        for anim in self.animations.values():
            for i in range(len(anim.frames)):
                out.append(Frame(f"{prefix}_{anim.key}_{i}", self.render(anim, i, look, outline)))
        return out

    def metadata(self, prefix: str | None = None, pivot: str | tuple[float, float] = "bottom") -> dict:
        """Engine-neutral animation data for ``<name>.anim.json``."""
        prefix = prefix or self.name
        return {
            "name": prefix,
            "frameSize": list(self.frame_size),
            "pivot": list(pivot) if isinstance(pivot, tuple) else pivot,
            "animations": [
                {"name": a.name, "direction": a.direction, "fps": a.fps, "loop": a.loop,
                 "frames": [f"{prefix}_{a.key}_{i}" for i in range(len(a.frames))]}
                for a in self.animations.values()
            ],
        }


def export_rig(project: ProjectConfig, rig: Rig, look: Look, name: str, target: str = "unity",
               path: Path | None = None, pivot: str | tuple[float, float] = "bottom", columns: int = 8,
               validate: bool = True) -> list[Path]:
    """Renders ``rig`` in ``look``, packs every frame into one texture named
    ``name`` (frames ``<name>_<anim>_<dir>_<i>``), exports it and writes
    ``<name>.anim.json`` beside it. A custom ``pivot`` (x, y) is measured
    from the frame's bottom-left corner, e.g. at the feet."""
    frames = rig.frames(look, project.shading.outline, prefix=name)
    if validate:
        failures = [validate_image(f.image, project.palette, project.allow_partial_alpha, f.name)
                    for f in frames]
        failures = [r.describe() for r in failures if not r.ok]
        if failures:
            raise ExportError("palette check failed:\n  " + "\n  ".join(failures[:10]))
    sheet = pack(frames, 0, min(columns, len(frames)), project.pack.max_width)
    exporter = create_exporter(project, target, path)
    written = exporter.export(ExportAsset(name, sheet.image, sheet.sprites, pivot))
    meta_path = exporter.output.path / f"{name}.anim.json"
    meta_path.write_text(json.dumps(rig.metadata(name, pivot), indent=1) + "\n",
                         encoding="utf-8", newline="\n")
    return written + [meta_path]
