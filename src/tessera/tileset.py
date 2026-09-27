"""Auto-tiling: tile sets whose piece depends on the neighboring cells.

Two layouts:

- ``blob``: 8 neighbors, the classic 47-piece set for terrain (paths, sand,
  water, soil). A diagonal only counts when both cardinals next to it are the
  same terrain, which folds the 256 neighbor masks down to 47 pieces.
- ``cardinal``: 4 neighbors, 16 pieces, for things that connect in lines
  (fences, walls, hedges).

Plus ``random`` (one cell, several variants) for base ground.

A game draws each piece from its mask (``draw(mask, frame)``); this module
names the pieces, writes the neighbor rules and exports the lot. Piece names
are ``<set>_<mask>`` and never change, so engine references survive
re-exports. The rules go to ``<set>.tileset.json`` beside the texture, in an
engine-neutral form (directions N, NE, E ... and "this" / "not this"); each
engine target builds its own tile assets from it.

Coordinates are image coordinates: x right, y down, so N is (0, -1).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Sequence

from PIL import Image

from tessera.config import ProjectConfig
from tessera.exporters import ExportAsset, ExportError, create_exporter
from tessera.pack import Frame, pack
from tessera.palette import validate_image

N, NE, E, SE, S, SW, W, NW = 1, 2, 4, 8, 16, 32, 64, 128
DIRECTIONS = {"N": N, "NE": NE, "E": E, "SE": SE, "S": S, "SW": SW, "W": W, "NW": NW}
OFFSETS = {N: (0, -1), NE: (1, -1), E: (1, 0), SE: (1, 1),
           S: (0, 1), SW: (-1, 1), W: (-1, 0), NW: (-1, -1)}
CARDINALS = N | E | S | W
COLLIDERS = ("none", "grid", "sprite")

# Quadrant cases for blob shapes (see ``quadrant_case``).
FILL, NOTCH, EDGE_X, EDGE_Y, CORNER = "fill", "notch", "edge_x", "edge_y", "corner"


def reduce_blob(mask: int) -> int:
    """Drops diagonals that do not matter (a cardinal next to them is open)."""
    for diagonal, (a, b) in ((NE, (N, E)), (SE, (S, E)), (SW, (S, W)), (NW, (N, W))):
        if not (mask & a and mask & b):
            mask &= ~diagonal
    return mask


BLOB_MASKS: tuple[int, ...] = tuple(sorted({reduce_blob(m) for m in range(256)}))
CARDINAL_MASKS: tuple[int, ...] = tuple(sorted({m & CARDINALS for m in range(256)}))


def mask_at(cells: set[tuple[int, int]], x: int, y: int, layout: str = "blob") -> int:
    """The neighbor mask of cell (x, y) within ``cells``."""
    mask = 0
    for bit, (dx, dy) in OFFSETS.items():
        if (x + dx, y + dy) in cells:
            mask |= bit
    return reduce_blob(mask) if layout == "blob" else mask & CARDINALS


def relevant_bits(mask: int, layout: str) -> int:
    """The neighbors a rule for this piece must check."""
    if layout == "cardinal":
        return CARDINALS
    bits = CARDINALS
    for diagonal, (a, b) in ((NE, (N, E)), (SE, (S, E)), (SW, (S, W)), (NW, (N, W))):
        if mask & a and mask & b:
            bits |= diagonal
    return bits


def quadrant_case(mask: int, right: bool, bottom: bool) -> str:
    """How one quarter of a blob tile meets its surroundings.

    FILL: both adjacent cardinals and the diagonal are terrain. NOTCH: both
    cardinals but not the diagonal (an inner corner). EDGE_X: the horizontal
    neighbor is open (a vertical border on the left/right side). EDGE_Y: the
    vertical neighbor is open. CORNER: both are open (an outer corner).
    """
    v = S if bottom else N
    h = E if right else W
    d = (SE if right else SW) if bottom else (NE if right else NW)
    has_v, has_h = bool(mask & v), bool(mask & h)
    if has_v and has_h:
        return FILL if mask & d else NOTCH
    if has_v:
        return EDGE_X
    if has_h:
        return EDGE_Y
    return CORNER


def blob_inside(mask: int, size: int, depth: Sequence[int], x: int, y: int) -> bool:
    """Whether pixel (x, y) of a blob tile belongs to the terrain.

    ``depth[t]`` is how far the border sits in from the tile edge at position
    t along that edge (0..size-1). Every edge reads the same sequence, so
    borders line up between neighboring tiles when ``depth`` wraps cleanly
    (depth[0] close to depth[-1]). Outer and inner corners are rounded with
    the local depth as radius. Pixels outside the tile answer for the
    neighbor on that side: terrain if that neighbor is.
    """
    if not (0 <= x < size and 0 <= y < size):
        dx = -1 if x < 0 else 1 if x >= size else 0
        dy = -1 if y < 0 else 1 if y >= size else 0
        bit = next(b for b, off in OFFSETS.items() if off == (dx, dy))
        return bool(mask & bit)
    right, bottom = x >= size // 2, y >= size // 2
    case = quadrant_case(mask, right, bottom)
    if case == FILL:
        return True
    # distance into the tile from the vertical and horizontal borders
    fx = size - 1 - x if right else x
    fy = size - 1 - y if bottom else y
    dx_border = depth[y % size]      # the border running down the left/right side
    dy_border = depth[x % size]      # the border running along the top/bottom
    if case == EDGE_X:
        return fx >= dx_border
    if case == EDGE_Y:
        return fy >= dy_border
    if case == CORNER:
        if fx < dx_border or fy < dy_border:
            return False
        r = min(dx_border, dy_border)
        cx, cy = dx_border + r, dy_border + r
        if fx < cx and fy < cy:
            return (cx - fx - 0.5) ** 2 + (cy - fy - 0.5) ** 2 <= r * r + 0.5
        return True
    # NOTCH: open in the corner square where the neighbors' borders meet,
    # its inner corner rounded
    if not (fx < dx_border and fy < dy_border):
        return True
    r = min(dx_border, dy_border) // 2
    cx, cy = dx_border - r, dy_border - r
    if fx >= cx and fy >= cy:
        return (fx + 0.5 - cx) ** 2 + (fy + 0.5 - cy) ** 2 > r * r + 0.5
    return False


def blob_field(mask: int, size: int, depth: Sequence[int], margin: int = 2) -> dict[tuple[int, int], bool]:
    """``blob_inside`` for the tile plus a margin, for border shading."""
    return {(x, y): blob_inside(mask, size, depth, x, y)
            for y in range(-margin, size + margin) for x in range(-margin, size + margin)}


def distance_inside(field_: dict[tuple[int, int], bool], size: int, limit: int = 6) -> dict[tuple[int, int], int]:
    """For each inside pixel of the tile: steps (4-connected) to the nearest
    outside pixel, capped at ``limit``. Outside pixels are 0."""
    dist = {p: (0 if not v else limit) for p, v in field_.items()}
    frontier = [p for p, v in field_.items() if not v]
    step = 0
    while frontier and step < limit:
        step += 1
        nxt = []
        for x, y in frontier:
            for q in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                if q in dist and dist[q] > step:
                    dist[q] = step
                    nxt.append(q)
        frontier = nxt
    return {(x, y): d for (x, y), d in dist.items() if 0 <= x < size and 0 <= y < size}


# Tile sets ------------------------------------------------------------------

@dataclass
class TileRule:
    frames: list[str]
    this: list[str] = field(default_factory=list)
    not_this: list[str] = field(default_factory=list)


@dataclass
class Tileset:
    name: str
    layout: str                       # blob | cardinal | random
    tile_size: int
    images: dict[str, Image.Image]    # sprite name -> image, in export order
    rules: list[TileRule]
    fps: float = 0.0                  # > 0: each rule's frames animate
    collider: str = "none"
    preview: str = ""                 # sprite shown in palettes

    def __post_init__(self):
        if self.layout not in ("blob", "cardinal", "random"):
            raise ExportError(f"{self.name}: unknown layout '{self.layout}'")
        if self.collider not in COLLIDERS:
            raise ExportError(f"{self.name}: collider must be one of {', '.join(COLLIDERS)}")
        for name, image in self.images.items():
            if image.size != (self.tile_size, self.tile_size):
                raise ExportError(f"{name}: {image.size} is not {self.tile_size}px square")
        self.preview = self.preview or self.rules[0].frames[0]

    def to_json(self) -> dict:
        return {
            "name": self.name,
            "layout": self.layout,
            "tileSize": self.tile_size,
            "fps": self.fps,
            "collider": self.collider,
            "preview": self.preview,
            "rules": [{"frames": r.frames, "this": r.this, "notThis": r.not_this} for r in self.rules],
        }

    def piece(self, mask: int, frame: int = 0) -> Image.Image:
        """The image the rules pick for a neighbor mask (for previews)."""
        return self.images[self.rules[self._rule_index(mask)].frames[frame % len(self.rules[0].frames)]]

    def _rule_index(self, mask: int) -> int:
        for index, rule in enumerate(self.rules):
            if all(mask & DIRECTIONS[d] for d in rule.this) and not any(mask & DIRECTIONS[d] for d in rule.not_this):
                return index
        raise ExportError(f"{self.name}: no rule matches mask {mask}")


def _neighbor_rule(frames: list[str], mask: int, layout: str) -> TileRule:
    bits = relevant_bits(mask, layout)
    this = [d for d, b in DIRECTIONS.items() if bits & b and mask & b]
    not_this = [d for d, b in DIRECTIONS.items() if bits & b and not mask & b]
    return TileRule(frames, this, not_this)


def connected_tileset(name: str, layout: str, tile_size: int,
                      draw: Callable[[int, int], Image.Image], frames: int = 1, fps: float = 0.0,
                      collider: str = "none", preview_mask: int | None = None) -> Tileset:
    """A blob or cardinal set: ``draw(mask, frame)`` for every piece."""
    masks = BLOB_MASKS if layout == "blob" else CARDINAL_MASKS
    images: dict[str, Image.Image] = {}
    rules = []
    for mask in masks:
        names = []
        for frame in range(frames):
            sprite = f"{name}_{mask}" + (f"_f{frame}" if frames > 1 else "")
            images[sprite] = draw(mask, frame)
            names.append(sprite)
        rules.append(_neighbor_rule(names, mask, layout))
    # Most specific rules first, so an engine that takes the first match agrees.
    rules.sort(key=lambda r: -(len(r.this) + len(r.not_this)))
    preview = ""
    if preview_mask is not None:
        preview = f"{name}_{preview_mask}" + ("_f0" if frames > 1 else "")
    return Tileset(name, layout, tile_size, images, rules, fps, collider, preview)


def random_tileset(name: str, variants: list[Image.Image], collider: str = "none") -> Tileset:
    images = {f"{name}_{i}": image for i, image in enumerate(variants)}
    tile_size = variants[0].width
    return Tileset(name, "random", tile_size, images, [TileRule(list(images))], 0.0, collider)


def export_tileset(project: ProjectConfig, tileset: Tileset, target: str = "unity",
                   columns: int = 8, validate: bool = True) -> list[Path]:
    """Packs the pieces into one texture, exports it and writes the rules."""
    if tileset.tile_size != project.grid.tile_size:
        raise ExportError(f"{tileset.name}: tiles are {tileset.tile_size}px, the project uses "
                          f"{project.grid.tile_size}px")
    if validate:
        failures = [validate_image(img, project.palette, project.allow_partial_alpha, name)
                    for name, img in tileset.images.items()]
        failures = [r.describe() for r in failures if not r.ok]
        if failures:
            raise ExportError("palette check failed:\n  " + "\n  ".join(failures[:10]))
    frames = [Frame(n, img) for n, img in tileset.images.items()]
    sheet = pack(frames, 0, min(columns, len(frames)), project.pack.max_width)
    exporter = create_exporter(project, target)
    written = exporter.export(ExportAsset(tileset.name, sheet.image, sheet.sprites, "center"))
    rules_path = exporter.output.path / f"{tileset.name}.tileset.json"
    rules_path.write_text(json.dumps(tileset.to_json(), indent=1) + "\n", encoding="utf-8", newline="\n")
    return written + [rules_path]


def render_cells(layers: list[tuple[Tileset, set[tuple[int, int]]]], cols: int, rows: int,
                 frame: int = 0, background: tuple[int, int, int, int] = (0, 0, 0, 0),
                 pick: Callable[[Tileset, int, int], str] | None = None) -> Image.Image:
    """Paints cell sets with their tile sets, bottom layer first (a preview of
    what the engine will draw). ``pick`` chooses among random variants."""
    size = layers[0][0].tile_size
    image = Image.new("RGBA", (cols * size, rows * size), background)
    for tileset, cells in layers:
        for x, y in sorted(cells):
            if tileset.layout == "random":
                names = tileset.rules[0].frames
                sprite = tileset.images[pick(tileset, x, y) if pick else names[(x * 7 + y * 13) % len(names)]]
            else:
                sprite = tileset.piece(mask_at(cells, x, y, tileset.layout), frame)
            image.alpha_composite(sprite, (x * size, y * size))
    return image
