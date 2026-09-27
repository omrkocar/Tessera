"""Project config: everything game-specific lives here, never in tool code.

A project is a folder with a ``tessera.toml``. Paths inside it are relative to
that folder. Unknown keys are rejected so a typo never silently falls back to
a default.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from tessera.palette import Palette, parse_color

CONFIG_FILE_NAME = "tessera.toml"

LIGHT_DIRECTIONS = (
    "top-left", "top", "top-right", "left", "right",
    "bottom-left", "bottom", "bottom-right",
)
OUTLINE_STYLES = ("none", "dark", "selective")
PIVOTS = {
    "center": (0.5, 0.5),
    "top-left": (0.0, 1.0),
    "top": (0.5, 1.0),
    "top-right": (1.0, 1.0),
    "left": (0.0, 0.5),
    "right": (1.0, 0.5),
    "bottom-left": (0.0, 0.0),
    "bottom": (0.5, 0.0),
    "bottom-right": (1.0, 0.0),
}


class ConfigError(Exception):
    """The project config is missing, malformed or has invalid values."""


@dataclass(frozen=True)
class GridConfig:
    tile_size: int
    pixels_per_unit: int


@dataclass(frozen=True)
class ShadingConfig:
    light_direction: str = "top-left"
    outline: str = "none"
    max_ramp: int = 4


@dataclass(frozen=True)
class PreviewConfig:
    scale: int = 8
    background: tuple[int, int, int, int] | None = None  # None = checkerboard
    grid_color: tuple[int, int, int, int] = (255, 255, 255, 40)


@dataclass(frozen=True)
class PackConfig:
    padding: int = 0
    max_width: int = 2048


@dataclass(frozen=True)
class OutputConfig:
    target: str
    path: Path
    pivot: str = "center"
    options: dict = field(default_factory=dict)


@dataclass(frozen=True)
class ProjectConfig:
    name: str
    root: Path
    palette: Palette
    allow_partial_alpha: bool
    grid: GridConfig
    shading: ShadingConfig
    preview: PreviewConfig
    pack: PackConfig
    outputs: tuple[OutputConfig, ...]

    def output(self, target: str) -> OutputConfig:
        for output in self.outputs:
            if output.target == target:
                return output
        known = ", ".join(o.target for o in self.outputs) or "none"
        raise ConfigError(f"no output with target '{target}' (configured: {known})")


def find_config(start: Path) -> Path:
    """Returns the tessera.toml at ``start`` (file or folder) or in a parent."""
    start = start.resolve()
    if start.is_file():
        return start
    for folder in (start, *start.parents):
        candidate = folder / CONFIG_FILE_NAME
        if candidate.is_file():
            return candidate
    raise ConfigError(f"no {CONFIG_FILE_NAME} found in {start} or its parents")


def load_config(path: Path) -> ProjectConfig:
    path = find_config(path)
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as error:
        raise ConfigError(f"{path}: {error}") from error
    return parse_config(data, path.parent)


def parse_config(data: dict, root: Path) -> ProjectConfig:
    reader = _Reader(data)
    project = reader.table("project", required=True)
    name = project.string("name", required=True)

    palette_table = reader.table("palette", required=True)
    palette = _read_palette(palette_table, root)
    max_colors = palette_table.integer("max_colors", default=None, minimum=1)
    if max_colors is not None and len(palette) > max_colors:
        palette_table.errors.append(
            f"palette: {len(palette)} colors, more than max_colors = {max_colors}")
    allow_partial_alpha = palette_table.boolean("allow_partial_alpha", default=False)

    grid_table = reader.table("grid", required=True)
    tile_size = grid_table.integer("tile_size", required=True, minimum=1)
    grid = GridConfig(
        tile_size=tile_size,
        pixels_per_unit=grid_table.integer("pixels_per_unit", default=tile_size, minimum=1),
    )

    shading_table = reader.table("shading")
    shading = ShadingConfig(
        light_direction=shading_table.choice("light_direction", LIGHT_DIRECTIONS, default="top-left"),
        outline=shading_table.choice("outline", OUTLINE_STYLES, default="none"),
        max_ramp=shading_table.integer("max_ramp", default=4, minimum=1),
    )

    preview_table = reader.table("preview")
    background = preview_table.string("background", default="checker")
    preview = PreviewConfig(
        scale=preview_table.integer("scale", default=8, minimum=1),
        background=None if background == "checker" else preview_table.color("background", background),
        grid_color=preview_table.color("grid_color", preview_table.string("grid_color", default="#ffffff28")),
    )

    pack_table = reader.table("pack")
    pack = PackConfig(
        padding=pack_table.integer("padding", default=0, minimum=0),
        max_width=pack_table.integer("max_width", default=2048, minimum=1),
    )

    outputs = []
    for output_table in reader.table_array("outputs"):
        target = output_table.string("target", required=True)
        output_path = output_table.string("path", required=True)
        pivot = output_table.choice("pivot", tuple(PIVOTS), default="center")
        options = output_table.rest()
        if target and output_path:
            outputs.append(OutputConfig(target, (root / output_path).resolve(), pivot, options))

    reader.finish()
    if reader.all_errors():
        raise ConfigError("invalid config:\n  " + "\n  ".join(reader.all_errors()))

    return ProjectConfig(
        name=name, root=root.resolve(), palette=palette,
        allow_partial_alpha=allow_partial_alpha, grid=grid, shading=shading,
        preview=preview, pack=pack, outputs=tuple(outputs),
    )


def _read_palette(table: "_Reader", root: Path) -> Palette:
    file_name = table.string("file", default=None)
    colors = table.list("colors", default=None)
    if (file_name is None) == (colors is None):
        table.errors.append("palette: set exactly one of 'file' or 'colors'")
        return Palette([])
    try:
        if file_name is not None:
            return Palette.load(root / file_name)
        return Palette([parse_color(c) for c in colors])
    except (OSError, ValueError) as error:
        table.errors.append(f"palette: {error}")
        return Palette([])


class _Reader:
    """Reads one TOML table, collecting errors instead of failing on the first."""

    def __init__(self, data: dict, prefix: str = ""):
        self.data = dict(data)
        self.prefix = prefix
        self.errors: list[str] = []
        self.children: list[_Reader] = []
        self.seen: set[str] = set()
        self.open = False  # tables whose remaining keys are passed through

    def _key(self, key: str) -> str:
        return f"{self.prefix}{key}"

    def _get(self, key, required, default, kinds, kind_name):
        self.seen.add(key)
        if key not in self.data:
            if required:
                self.errors.append(f"{self._key(key)}: required")
            return default
        value = self.data[key]
        if not isinstance(value, kinds) or (kinds is int and isinstance(value, bool)):
            self.errors.append(f"{self._key(key)}: expected {kind_name}, got {value!r}")
            return default
        return value

    def table(self, key: str, required: bool = False) -> "_Reader":
        value = self._get(key, required, {}, dict, "a table")
        child = _Reader(value, f"{self._key(key)}.")
        self.children.append(child)
        return child

    def table_array(self, key: str) -> list["_Reader"]:
        values = self._get(key, False, [], list, "an array of tables")
        children = []
        for index, value in enumerate(values):
            if not isinstance(value, dict):
                self.errors.append(f"{self._key(key)}[{index}]: expected a table")
                continue
            child = _Reader(value, f"{self._key(key)}[{index}].")
            self.children.append(child)
            children.append(child)
        return children

    def string(self, key, required=False, default=None):
        return self._get(key, required, default, str, "a string")

    def boolean(self, key, required=False, default=None):
        return self._get(key, required, default, bool, "true or false")

    def list(self, key, required=False, default=None):
        return self._get(key, required, default, list, "a list")

    def integer(self, key, required=False, default=None, minimum=None):
        value = self._get(key, required, default, int, "an integer")
        if value is not None and minimum is not None and value < minimum:
            self.errors.append(f"{self._key(key)}: must be at least {minimum}, got {value}")
            return default
        return value

    def choice(self, key, choices, default=None):
        value = self.string(key, default=default)
        if value not in choices:
            self.errors.append(f"{self._key(key)}: must be one of {', '.join(choices)}, got {value!r}")
            return default
        return value

    def color(self, key, text):
        try:
            return parse_color(text)
        except ValueError as error:
            self.errors.append(f"{self._key(key)}: {error}")
            return (0, 0, 0, 255)

    def rest(self) -> dict:
        """Returns the keys not read yet; they belong to the output target."""
        self.open = True
        return {k: v for k, v in self.data.items() if k not in self.seen}

    def finish(self):
        if not self.open:
            for key in self.data:
                if key not in self.seen:
                    self.errors.append(f"{self._key(key)}: unknown key")
        for child in self.children:
            child.finish()

    def all_errors(self) -> list[str]:
        errors = list(self.errors)
        for child in self.children:
            errors.extend(child.all_errors())
        return errors
