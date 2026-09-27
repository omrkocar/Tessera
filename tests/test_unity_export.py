import re

import pytest
from PIL import Image

from conftest import BLUE, RED, solid
from tessera.config import load_config
from tessera.exporters import ExportAsset, ExportError, create_exporter
from tessera.exporters.unity import internal_id, sprite_id
from tessera.pack import SpriteRect


def exporter(project_dir, **options):
    project = load_config(project_dir)
    exp = create_exporter(project, "unity")
    exp.output.options.update(options)
    return exp


def field(meta: str, name: str) -> str:
    return re.search(rf"^\s*{name}: (.*)$", meta, re.MULTILINE).group(1)


def test_single_sprite_meta_is_pixel_perfect(project_dir):
    exp = exporter(project_dir)
    png, meta_path = exp.export(ExportAsset.whole("crate", solid((16, 16), RED), "bottom"))
    meta = meta_path.read_text(encoding="utf-8")
    assert png.name == "crate.png" and Image.open(png).getpixel((0, 0)) == RED
    assert field(meta, "filterMode") == "0"          # point
    assert field(meta, "enableMipMap") == "0"
    assert set(re.findall(r"textureCompression: (\d+)", meta)) == {"0"}
    assert field(meta, "spritePixelsToUnits") == "16"
    assert field(meta, "spriteMode") == "1"          # single
    assert field(meta, "alignment") == "7"           # bottom center
    assert field(meta, "spritePivot") == "{x: 0.5, y: 0.0}"
    assert field(meta, "maxTextureSize") == "32"
    guid = field(meta, "guid")
    assert f"    spriteID: {sprite_id(guid, 'crate')}\n" in meta  # never empty in single mode
    assert re.findall(r"buildTarget: (\w+)", meta) == [
        "DefaultTexturePlatform", "Standalone", "iOS", "Android"]


def test_sheet_meta_flips_y_and_lists_sprites(project_dir):
    image = Image.new("RGBA", (32, 48))
    sprites = (SpriteRect("top", 0, 0, 16, 16), SpriteRect("bottom", 16, 32, 16, 16))
    exp = exporter(project_dir)
    meta = exp.meta_text(ExportAsset("walk", image, sprites), guid="0" * 32)
    assert field(meta, "spriteMode") == "2"
    blocks = meta.split("    - serializedVersion: 2\n")[1:]
    assert "name: top" in blocks[0] and "y: 32" in blocks[0]      # 48 - 0 - 16
    assert "name: bottom" in blocks[1] and "x: 16" in blocks[1] and "        y: 0" in blocks[1]
    assert f"top: {internal_id('0' * 32, 'top')}" in meta
    assert field(meta, "maxTextureSize") == "64"


def test_reexport_keeps_guid_and_sprite_ids(project_dir):
    exp = exporter(project_dir)
    frames = (SpriteRect("a", 0, 0, 8, 8), SpriteRect("b", 8, 0, 8, 8))
    _, meta_path = exp.export(ExportAsset("anim", solid((16, 8), BLUE), frames))
    first = meta_path.read_text(encoding="utf-8")
    _, meta_path = exp.export(ExportAsset("anim", solid((16, 8), RED), frames))
    second = meta_path.read_text(encoding="utf-8")
    assert field(first, "guid") == field(second, "guid")
    assert re.findall(r"spriteID: (\w+)", first) == re.findall(r"spriteID: (\w+)", second)


def test_ids_differ_per_name_and_are_nonzero():
    ids = {internal_id("a" * 32, f"s{i}") for i in range(200)}
    assert len(ids) == 200 and 0 not in ids


def test_invalid_assets_and_options(project_dir):
    with pytest.raises(ExportError, match="asset name"):
        ExportAsset.whole("bad name", solid((4, 4), RED))
    with pytest.raises(ExportError, match="outside"):
        ExportAsset("x", solid((4, 4), RED), (SpriteRect("s", 2, 2, 4, 4),))
    with pytest.raises(ExportError, match="unknown option"):
        exporter(project_dir, colour=True).export(ExportAsset.whole("x", solid((4, 4), RED)))
    with pytest.raises(ExportError, match="unknown export target"):
        create_exporter(load_config(project_dir), "godot")


def test_nine_slice_borders_are_written_left_bottom_right_top(project_dir):
    exp = exporter(project_dir)
    single = exp.meta_text(ExportAsset.whole("panel", solid((24, 24), RED), border=(5, 6, 7, 8)),
                           guid="0" * 32)
    assert field(single, "spriteBorder") == "{x: 5, y: 8, z: 7, w: 6}"
    sprites = (SpriteRect("a", 0, 0, 16, 16, (4, 4, 4, 4)), SpriteRect("b", 16, 0, 16, 16))
    sheet = exp.meta_text(ExportAsset("kit", solid((32, 16), RED), sprites), guid="0" * 32)
    borders = re.findall(r"      border: (.*)", sheet)
    assert borders == ["{x: 4, y: 4, z: 4, w: 4}", "{x: 0, y: 0, z: 0, w: 0}"]


def test_border_larger_than_the_sprite_is_rejected():
    with pytest.raises(ExportError, match="border"):
        ExportAsset.whole("panel", solid((8, 8), RED), border=(5, 0, 5, 0))
