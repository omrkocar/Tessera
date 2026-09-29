"""Pixel fonts: glyphs drawn as text rows, built into a TrueType font.

Every glyph is a list of rows of equal length; ``#`` is ink, anything else
is empty. All glyphs of a font have the same number of rows (``ascent``
rows above the baseline, ``descent`` rows below). The font's em is one
pixel row per ``ascent + descent``, so an engine that renders the font at
``font.em`` px (or an integer multiple) gets one screen pixel (or an
integer block) per glyph pixel, with no antialiasing on the edges.

Outlines are rectangles, one per horizontal run of ink, so the glyphs stay
exactly on the pixel grid.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image


class FontError(Exception):
    pass


@dataclass
class BitmapFont:
    family: str
    ascent: int
    descent: int
    spacing: int = 1                        # empty columns after each glyph
    space_width: int = 3
    line_gap: int = 1
    glyphs: dict[str, tuple[str, ...]] = field(default_factory=dict)
    # per-glyph spacing overrides: joining scripts (Arabic) draw their own
    # gaps and touch their neighbors, so their glyphs use 0
    spacings: dict[str, int] = field(default_factory=dict)

    @property
    def em(self) -> int:
        return self.ascent + self.descent

    def add(self, char: str, rows, spacing: int | None = None) -> None:
        """Adds a glyph; ``spacing`` overrides the font's for this glyph only."""
        rows = tuple(rows)
        if len(char) != 1:
            raise FontError(f"glyph key {char!r} must be one character")
        if len(rows) != self.em:
            raise FontError(f"glyph {char!r}: {len(rows)} rows, the font has {self.em}")
        widths = {len(r) for r in rows}
        if len(widths) != 1:
            raise FontError(f"glyph {char!r}: rows have different lengths {sorted(widths)}")
        if spacing is not None and spacing < 0:
            raise FontError(f"glyph {char!r}: spacing {spacing} must not be negative")
        self.glyphs[char] = rows
        if spacing is None:
            self.spacings.pop(char, None)
        else:
            self.spacings[char] = spacing

    def width(self, char: str) -> int:
        if char == " ":
            return self.space_width
        return len(self.glyphs[char][0])

    def advance(self, char: str) -> int:
        if char == " ":
            return self.width(char)
        return self.width(char) + self.spacings.get(char, self.spacing)

    def missing(self, text: str) -> list[str]:
        return sorted({c for c in text if c != " " and c not in self.glyphs})

    def render(self, text: str, ink=(255, 255, 255, 255)) -> Image.Image:
        """One line of text at 1x, for previews and checks."""
        missing = self.missing(text)
        if missing:
            raise FontError(f"no glyph for {''.join(missing)!r}")
        width = max(1, sum(self.advance(c) for c in text))
        img = Image.new("RGBA", (width, self.em), (0, 0, 0, 0))
        px = img.load()
        x = 0
        for c in text:
            if c != " ":
                for y, row in enumerate(self.glyphs[c]):
                    for dx, ch in enumerate(row):
                        if ch == "#":
                            px[x + dx, y] = ink
            x += self.advance(c)
        return img


def glyph_name(char: str) -> str:
    return f"uni{ord(char):04X}"


def runs(row: str):
    """(start, end) of each run of '#' in a row, end exclusive."""
    x = 0
    while x < len(row):
        if row[x] == "#":
            start = x
            while x < len(row) and row[x] == "#":
                x += 1
            yield start, x
        else:
            x += 1


def build_ttf(font: BitmapFont, path: Path, units_per_pixel: int = 128) -> Path:
    """Writes ``font`` as a TrueType file. One glyph pixel is
    ``units_per_pixel`` font units; the em is ``font.em`` pixels."""
    from fontTools.fontBuilder import FontBuilder
    from fontTools.pens.ttGlyphPen import TTGlyphPen

    u = units_per_pixel
    chars = sorted(font.glyphs)
    order = [".notdef", "space"] + [glyph_name(c) for c in chars]
    cmap = {ord(" "): "space"} | {ord(c): glyph_name(c) for c in chars}

    def empty():
        return TTGlyphPen(None).glyph()

    def notdef():
        pen = TTGlyphPen(None)
        h = font.ascent - 1
        for x0, y0, x1, y1 in ((0, 0, 4, 1), (0, h - 1, 4, h), (0, 1, 1, h - 1), (3, 1, 4, h - 1)):
            rect(pen, x0 * u, y0 * u, x1 * u, y1 * u)
        return pen.glyph()

    glyphs = {".notdef": notdef(), "space": empty()}
    metrics = {".notdef": (5 * u, 0), "space": (font.space_width * u, 0)}
    for c in chars:
        pen = TTGlyphPen(None)
        drawn = False
        left = None
        for y, row in enumerate(font.glyphs[c]):
            top = (font.ascent - y) * u          # row 0 is the top row
            for start, end in runs(row):
                rect(pen, start * u, top - u, end * u, top)
                drawn = True
                left = start if left is None else min(left, start)
        glyphs[glyph_name(c)] = pen.glyph() if drawn else empty()
        # the left side bearing must be the ink's left edge: rasterizers place
        # the outline by it, so 0 would shift a glyph with empty columns on its left
        metrics[glyph_name(c)] = (font.advance(c) * u, (left or 0) * u)

    fb = FontBuilder(font.em * u, isTTF=True)
    fb.setupGlyphOrder(order)
    fb.setupCharacterMap(cmap)
    fb.setupGlyf(glyphs)
    fb.setupHorizontalMetrics(metrics)
    ascent, descent, gap = font.ascent * u, font.descent * u, font.line_gap * u
    fb.setupHorizontalHeader(ascent=ascent, descent=-descent, lineGap=gap)
    fb.setupNameTable({"familyName": font.family, "styleName": "Regular"})
    fb.setupOS2(sTypoAscender=ascent, sTypoDescender=-descent, sTypoLineGap=gap,
                usWinAscent=ascent, usWinDescent=descent, fsType=0)
    fb.setupPost()
    path.parent.mkdir(parents=True, exist_ok=True)
    fb.save(str(path))
    return path


def rect(pen, x0, y0, x1, y1) -> None:
    """A clockwise rectangle (TrueType's fill direction)."""
    pen.moveTo((x0, y0))
    pen.lineTo((x0, y1))
    pen.lineTo((x1, y1))
    pen.lineTo((x1, y0))
    pen.closePath()
