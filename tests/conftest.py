from pathlib import Path

import pytest
from PIL import Image

RED, GREEN, BLUE, BLACK = (255, 0, 0, 255), (0, 255, 0, 255), (0, 0, 255, 255), (0, 0, 0, 255)

CONFIG = """
[project]
name = "test"

[palette]
colors = ["#ff0000", "#00ff00", "#0000ff", "#000000"]

[grid]
tile_size = 16
pixels_per_unit = 16

[[outputs]]
target = "unity"
path = "unity_out"
pivot = "bottom"
"""


@pytest.fixture
def project_dir(tmp_path: Path) -> Path:
    (tmp_path / "tessera.toml").write_text(CONFIG, encoding="utf-8")
    return tmp_path


def solid(size, color) -> Image.Image:
    return Image.new("RGBA", size, color)


def save_png(image: Image.Image, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)
    return path
