import json
import re

from PIL import Image

from conftest import BLUE, GREEN, RED, save_png, solid
from tessera.cli import main


def run(project_dir, *args):
    return main(["--project", str(project_dir), *args])


def test_validate_exit_codes(project_dir, capsys):
    good = save_png(solid((4, 4), RED), project_dir / "good.png")
    bad = save_png(solid((4, 4), (1, 2, 3, 255)), project_dir / "bad" / "bad.png")
    assert run(project_dir, "validate", str(good)) == 0
    assert run(project_dir, "validate", str(good), str(bad.parent)) == 1
    assert "1/2 passed" in capsys.readouterr().out


def test_export_single_sprite_end_to_end(project_dir):
    sprite = save_png(solid((16, 16), GREEN), project_dir / "sprites" / "bush.png")
    assert run(project_dir, "export", "unity", str(sprite)) == 0
    out = project_dir / "unity_out"
    assert Image.open(out / "bush.png").getpixel((15, 15)) == GREEN
    meta = (out / "bush.png.meta").read_text(encoding="utf-8")
    assert "filterMode: 0" in meta and "spriteMode: 1" in meta
    assert "alignment: 7" in meta  # the config's pivot


def test_export_sliced_sheet_with_override_folder(project_dir, tmp_path):
    sheet = Image.new("RGBA", (32, 16))
    sheet.paste(solid((16, 16), RED), (0, 0))
    sheet.paste(solid((16, 16), BLUE), (16, 0))
    path = save_png(sheet, project_dir / "walk.png")
    target = tmp_path / "elsewhere"
    assert run(project_dir, "export", "unity", str(path), "--slice", "16x16",
               "--pivot", "center", "--out", str(target)) == 0
    meta = (target / "walk.png.meta").read_text(encoding="utf-8")
    assert re.findall(r"name: (walk_\d)", meta) == ["walk_0", "walk_1"]
    assert "spriteMode: 2" in meta and "alignment: 0" in meta


def test_export_refuses_off_palette_art(project_dir, capsys):
    path = save_png(solid((4, 4), (9, 9, 9, 255)), project_dir / "x.png")
    assert run(project_dir, "export", "unity", str(path)) == 2
    assert "palette check failed" in capsys.readouterr().err
    assert not (project_dir / "unity_out" / "x.png").exists()
    assert run(project_dir, "export", "unity", str(path), "--no-validate") == 0


def test_pack_writes_sheet_and_json(project_dir):
    a = save_png(solid((8, 8), RED), project_dir / "f" / "a.png")
    b = save_png(solid((8, 8), BLUE), project_dir / "f" / "b.png")
    out = project_dir / "packed"
    assert run(project_dir, "pack", str(a), str(b), "--name", "pair", "-o", str(out)) == 0
    meta = json.loads((out / "pair.json").read_text(encoding="utf-8"))
    assert meta["size"] == [16, 8]
    assert [s["name"] for s in meta["sprites"]] == ["a", "b"]


def test_previews(project_dir):
    sprite = save_png(solid((16, 16), RED), project_dir / "t.png")
    assert run(project_dir, "preview", str(sprite), "--tile", "2x2", "--grid", "-o",
               str(project_dir / "p.png")) == 0
    assert Image.open(project_dir / "p.png").size == (256, 256)
    other = save_png(solid((16, 16), BLUE), project_dir / "u.png")
    assert run(project_dir, "strip", str(sprite), str(other), "-o", str(project_dir / "s.gif")) == 0
    with Image.open(project_dir / "s.gif") as gif:
        assert gif.n_frames == 2


def test_config_errors_exit_2(tmp_path, capsys):
    (tmp_path / "tessera.toml").write_text("[project]\n", encoding="utf-8")
    assert main(["--project", str(tmp_path), "info"]) == 2
    assert "project.name: required" in capsys.readouterr().err
