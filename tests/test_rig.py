import json

import pytest
from PIL import Image

from conftest import BLACK, BLUE, GREEN, RED
from tessera.config import load_config
from tessera.exporters import ExportError
from tessera.rig import Look, Part, Place, Rig, RigError, export_rig

LEGEND = {"a": ("body", 0), "b": ("body", 1), "c": ("body", 2), "x": ("cloth", 2)}
BODY = Look("test", {"body": [BLACK, RED, GREEN], "cloth": [BLACK, BLUE, BLUE]})


def make_rig() -> Rig:
    rig = Rig("hero", (6, 6), 3)
    rig.add_part(Part.from_rows("block", ["ccc", "ccc", "ccc"], LEGEND))
    rig.add_part(Part.from_rows("patch", ["xx", "xx"], LEGEND))
    rig.add_part(Part.from_rows("step", ["c..", "cc.", "ccc"], LEGEND))
    return rig


def test_from_rows_reads_legend_and_transparency():
    part = Part.from_rows("p", ["a.b", " c"], LEGEND)
    assert part.width == 3 and part.height == 2
    assert part.pixels == {(0, 0): ("body", 0), (2, 0): ("body", 1), (1, 1): ("body", 2)}


def test_unknown_character_is_an_error():
    with pytest.raises(RigError, match="'z'"):
        Part.from_rows("p", ["z"], LEGEND)


def test_level_outside_rig_is_an_error():
    rig = Rig("r", (4, 4), 2)
    with pytest.raises(RigError, match="level 2"):
        rig.add_part(Part.from_rows("p", ["c"], LEGEND))


def test_animation_with_unknown_part_is_an_error():
    rig = make_rig()
    with pytest.raises(RigError, match="unknown part"):
        rig.add_animation("idle", "down", [[Place("nope", 0, 0)]], 2)


def test_selective_outline_darkens_bottom_right_and_softens_top_left():
    rig = make_rig()
    anim = rig.add_animation("idle", "down", [[Place("block", 1, 1)]], 2)
    px = rig.render_pixels(anim, 0, "selective")
    assert px[(2, 2)] == ("body", 2)          # inside
    assert px[(1, 1)] == ("body", 1)          # top-left corner: one level down
    assert px[(2, 1)] == ("body", 1)          # top edge
    assert px[(3, 2)] == ("body", 0)          # right edge
    assert px[(2, 3)] == ("body", 0)          # bottom edge


def test_outline_only_against_parts_below():
    rig = make_rig()
    anim = rig.add_animation("idle", "down", [[Place("block", 0, 0), Place("patch", 1, 1)]], 2)
    px = rig.render_pixels(anim, 0, "dark")
    # the patch lies on the block: it is outlined, the block around it is not
    assert px[(1, 1)] == ("cloth", 0)
    assert px[(0, 1)] == ("body", 0)          # block's own outer edge
    assert rig.render_pixels(anim, 0, "none")[(1, 1)] == ("cloth", 2)


def test_parts_without_outline_keep_their_levels():
    rig = Rig("r", (4, 4), 3)
    rig.add_part(Part.from_rows("dot", ["c"], LEGEND, outline=False))
    anim = rig.add_animation("idle", "down", [[Place("dot", 1, 1)]], 2)
    assert rig.render_pixels(anim, 0, "selective") == {(1, 1): ("body", 2)}


def test_left_mirrors_right():
    rig = make_rig()
    rig.add_animation("walk", "right", [[Place("step", 0, 3)]], 8)
    rig.mirror_left()
    right = rig.render(rig.animations["walk_right"], 0, BODY, "none")
    left = rig.render(rig.animations["walk_left"], 0, BODY, "none")
    assert left.tobytes() == right.transpose(Image.Transpose.FLIP_LEFT_RIGHT).tobytes()


def test_explicit_left_is_not_mirrored():
    rig = make_rig()
    rig.add_animation("walk", "right", [[Place("step", 0, 0)]], 8)
    rig.add_animation("walk", "left", [[Place("step", 0, 0)]], 8)
    rig.mirror_left()
    assert not rig.is_mirrored(rig.animations["walk_left"])


def test_look_recolors_slots():
    rig = make_rig()
    anim = rig.add_animation("idle", "down", [[Place("patch", 0, 0)]], 2)
    other = Look("other", {"body": [BLACK, RED, GREEN], "cloth": [BLACK, RED, RED]})
    assert rig.render(anim, 0, BODY, "none").getpixel((0, 0)) == BLUE
    assert rig.render(anim, 0, other, "none").getpixel((0, 0)) == RED


def test_look_missing_a_slot_is_an_error():
    rig = make_rig()
    anim = rig.add_animation("idle", "down", [[Place("patch", 0, 0)]], 2)
    with pytest.raises(RigError, match="cloth"):
        rig.render(anim, 0, Look("bare", {"body": [BLACK, RED, GREEN]}), "none")


def test_export_writes_sheet_meta_and_animation_data(project_dir):
    project = load_config(project_dir)
    rig = make_rig()
    rig.add_animation("idle", "down", [[Place("block", 1, 1)], [Place("block", 1, 2)]], 2)
    rig.add_animation("walk", "right", [[Place("step", 0, 3)]], 8, loop=True)
    rig.mirror_left()
    written = export_rig(project, rig, BODY, "hero", pivot=(0.5, 0.25))
    names = sorted(p.name for p in written)
    assert names == ["hero.anim.json", "hero.png", "hero.png.meta"]
    data = json.loads((project_dir / "unity_out" / "hero.anim.json").read_text())
    assert data["pivot"] == [0.5, 0.25]
    assert [a["name"] + "_" + a["direction"] for a in data["animations"]] == [
        "idle_down", "walk_right", "walk_left"]
    assert data["animations"][0]["frames"] == ["hero_idle_down_0", "hero_idle_down_1"]
    meta = (project_dir / "unity_out" / "hero.png.meta").read_text()
    assert "alignment: 9" in meta and "pivot: {x: 0.5, y: 0.25}" in meta
    assert "name: hero_walk_left_0" in meta


def test_export_rejects_off_palette_looks(project_dir):
    project = load_config(project_dir)
    rig = make_rig()
    rig.add_animation("idle", "down", [[Place("block", 0, 0)]], 2)
    odd = Look("odd", {"body": [BLACK, RED, (1, 2, 3, 255)], "cloth": [BLACK, BLUE, BLUE]})
    with pytest.raises(ExportError, match="palette"):
        export_rig(project, rig, odd, "hero")
