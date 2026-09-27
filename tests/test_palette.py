import pytest
from PIL import Image

from conftest import BLACK, BLUE, GREEN, RED, solid
from tessera.palette import Palette, format_color, parse_color, validate_image


def palette():
    return Palette([RED, GREEN, BLUE, BLACK])


def test_parse_color_forms():
    assert parse_color("#FF0000") == RED
    assert parse_color("00ff00") == GREEN
    assert parse_color("#0000ff80") == (0, 0, 255, 128)
    assert format_color((0, 0, 255, 128)) == "#0000ff80"
    with pytest.raises(ValueError):
        parse_color("#12345")
    with pytest.raises(ValueError):
        parse_color("#gggggg")


def test_palette_rejects_duplicates_and_alpha():
    with pytest.raises(ValueError, match="duplicate"):
        Palette([RED, RED])
    with pytest.raises(ValueError, match="opaque"):
        Palette([(1, 2, 3, 100)])


def test_load_hex_and_gpl(tmp_path):
    hex_file = tmp_path / "p.hex"
    hex_file.write_text("; comment\nff0000\n\n00ff00 ; green\n", encoding="utf-8")
    assert Palette.load(hex_file).colors == [RED, GREEN]
    gpl = tmp_path / "p.gpl"
    gpl.write_text("GIMP Palette\nName: x\nColumns: 4\n#\n255   0   0 red\n  0   0 255\tblue\n",
                   encoding="utf-8")
    assert Palette.load(gpl).colors == [RED, BLUE]


def test_clean_image_passes_and_transparent_pixels_are_ignored():
    image = solid((4, 4), RED)
    image.putpixel((1, 1), (12, 34, 56, 0))  # invisible, any RGB
    assert validate_image(image, palette()).ok


def test_off_palette_pixel_is_reported_with_position():
    image = solid((4, 4), RED)
    image.putpixel((3, 2), (254, 0, 0, 255))
    report = validate_image(image, palette(), name="x")
    assert not report.ok
    assert report.off_palette == 1
    assert report.samples[0][:2] == (3, 2)
    assert "#fe0000" in report.describe()


def test_partial_alpha_fails_unless_allowed():
    image = solid((2, 2), RED)
    image.putpixel((0, 0), (0, 255, 0, 128))
    assert validate_image(image, palette()).partial_alpha == 1
    assert validate_image(image, palette(), allow_partial_alpha=True).ok


def test_non_rgba_images_are_converted():
    image = Image.new("RGB", (2, 2), (0, 0, 255))
    assert validate_image(image, palette()).ok
