"""Palettes and the off-palette check.

A pixel passes when it is fully transparent, or opaque and exactly one of the
palette colors. Partial alpha fails unless the project allows it (and then its
RGB must still be a palette color).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image

Color = tuple[int, int, int, int]


def parse_color(text: str) -> Color:
    """Parses '#rrggbb', '#rrggbbaa', 'rrggbb' or 'rrggbbaa'."""
    value = text.strip().lstrip("#")
    if len(value) not in (6, 8) or any(c not in "0123456789abcdefABCDEF" for c in value):
        raise ValueError(f"not a hex color: {text!r}")
    channels = [int(value[i:i + 2], 16) for i in range(0, len(value), 2)]
    if len(channels) == 3:
        channels.append(255)
    return tuple(channels)  # type: ignore[return-value]


def format_color(color: Color) -> str:
    text = "#{:02x}{:02x}{:02x}".format(*color[:3])
    return text if color[3] == 255 else text + f"{color[3]:02x}"


class Palette:
    def __init__(self, colors: list[Color]):
        seen: set[tuple[int, int, int]] = set()
        duplicates = []
        for color in colors:
            if color[3] != 255:
                raise ValueError(f"palette colors must be opaque: {format_color(color)}")
            if color[:3] in seen:
                duplicates.append(format_color(color))
            seen.add(color[:3])
        if duplicates:
            raise ValueError(f"duplicate palette colors: {', '.join(duplicates)}")
        self.colors = list(colors)
        self._rgb = seen

    def __len__(self) -> int:
        return len(self.colors)

    def __contains__(self, rgb) -> bool:
        return tuple(rgb[:3]) in self._rgb

    @staticmethod
    def load(path: Path) -> "Palette":
        """Loads a Lospec-style .hex file (one color per line) or a GIMP .gpl."""
        text = path.read_text(encoding="utf-8")
        if path.suffix.lower() == ".gpl":
            return Palette(_parse_gpl(text))
        colors = []
        for line in text.splitlines():
            line = line.split(";", 1)[0].strip()
            if line:
                colors.append(parse_color(line))
        return Palette(colors)


def _parse_gpl(text: str) -> list[Color]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "GIMP Palette":
        raise ValueError("not a GIMP palette (first line must be 'GIMP Palette')")
    colors = []
    for line in lines[1:]:
        line = line.strip()
        if not line or line.startswith("#") or ":" in line.split()[0]:
            continue
        parts = line.split()
        colors.append((int(parts[0]), int(parts[1]), int(parts[2]), 255))
    return colors


@dataclass
class ValidationReport:
    name: str
    size: tuple[int, int]
    off_palette: int = 0
    partial_alpha: int = 0
    samples: list[tuple[int, int, Color]] = field(default_factory=list)
    off_colors: set[Color] = field(default_factory=set)

    @property
    def ok(self) -> bool:
        return self.off_palette == 0 and self.partial_alpha == 0

    def describe(self, limit: int = 5) -> str:
        if self.ok:
            return f"{self.name}: ok ({self.size[0]}x{self.size[1]})"
        parts = []
        if self.off_palette:
            colors = ", ".join(sorted(format_color(c) for c in self.off_colors)[:limit])
            parts.append(f"{self.off_palette} off-palette pixel(s), colors {colors}")
        if self.partial_alpha:
            parts.append(f"{self.partial_alpha} partially transparent pixel(s)")
        where = ", ".join(f"({x},{y})" for x, y, _ in self.samples[:limit])
        return f"{self.name}: FAIL {'; '.join(parts)}; first at {where}"


def validate_image(image: Image.Image, palette: Palette, allow_partial_alpha: bool = False,
                   name: str = "image", sample_limit: int = 20) -> ValidationReport:
    image = image.convert("RGBA")
    report = ValidationReport(name=name, size=image.size)
    width = image.width
    data = image.tobytes()
    for index in range(len(data) // 4):
        pixel = tuple(data[index * 4:index * 4 + 4])
        alpha = pixel[3]
        if alpha == 0:
            continue
        bad = False
        if alpha != 255 and not allow_partial_alpha:
            report.partial_alpha += 1
            bad = True
        if pixel[:3] not in palette:
            report.off_palette += 1
            report.off_colors.add((*pixel[:3], 255))
            bad = True
        if bad and len(report.samples) < sample_limit:
            report.samples.append((index % width, index // width, pixel))
    return report
