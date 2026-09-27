"""The exporter interface. One class per engine target, registered by name;
the project config's ``[[outputs]]`` entries pick them."""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar

from PIL import Image

from tessera.config import PIVOTS, OutputConfig, ProjectConfig
from tessera.pack import SpriteRect

ASSET_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_\-]*$")


class ExportError(Exception):
    pass


@dataclass(frozen=True)
class ExportAsset:
    """One texture and the sprites cut from it (rects in image coordinates).
    ``pivot`` is a named pivot ("center", "bottom", ...) or a custom (x, y)
    in 0..1, measured from the sprite's bottom-left corner."""
    name: str
    image: Image.Image
    sprites: tuple[SpriteRect, ...]
    pivot: str | tuple[float, float] = "center"

    def __post_init__(self):
        if not ASSET_NAME.match(self.name):
            raise ExportError(f"asset name {self.name!r}: use letters, digits, '_' and '-'")
        if isinstance(self.pivot, tuple):
            if len(self.pivot) != 2 or not all(0 <= v <= 1 for v in self.pivot):
                raise ExportError(f"{self.name}: custom pivot must be (x, y) in 0..1")
        elif self.pivot not in PIVOTS:
            raise ExportError(f"{self.name}: unknown pivot '{self.pivot}'")
        for rect in self.sprites:
            if (rect.x < 0 or rect.y < 0 or rect.width < 1 or rect.height < 1
                    or rect.x + rect.width > self.image.width
                    or rect.y + rect.height > self.image.height):
                raise ExportError(f"sprite '{rect.name}' lies outside the {self.image.size} image")
            if rect.border is not None:
                left, top, right, bottom = rect.border
                if (min(rect.border) < 0 or left + right > rect.width
                        or top + bottom > rect.height):
                    raise ExportError(f"sprite '{rect.name}': border {rect.border} does not fit "
                                      f"{rect.width}x{rect.height}")

    @staticmethod
    def whole(name: str, image: Image.Image, pivot: str = "center",
              border: tuple[int, int, int, int] | None = None) -> "ExportAsset":
        rect = SpriteRect(name, 0, 0, image.width, image.height, border)
        return ExportAsset(name, image, (rect,), pivot)


class Exporter(ABC):
    target: ClassVar[str]

    def __init__(self, project: ProjectConfig, output: OutputConfig):
        self.project = project
        self.output = output

    @abstractmethod
    def export(self, asset: ExportAsset) -> list[Path]:
        """Writes the asset into ``output.path``; returns the files written."""


_REGISTRY: dict[str, type[Exporter]] = {}


def register(cls: type[Exporter]) -> type[Exporter]:
    _REGISTRY[cls.target] = cls
    return cls


def targets() -> list[str]:
    return sorted(_REGISTRY)


def create_exporter(project: ProjectConfig, target: str, path: Path | None = None) -> Exporter:
    if target not in _REGISTRY:
        raise ExportError(f"unknown export target '{target}' (known: {', '.join(targets())})")
    output = project.output(target)
    if path is not None:
        output = OutputConfig(output.target, path.resolve(), output.pivot, output.options)
    return _REGISTRY[target](project, output)
