import pytest
from PIL import Image, ImageFont, ImageDraw

from tessera.font import BitmapFont, FontError, build_ttf


def small_font() -> BitmapFont:
    font = BitmapFont("Test", ascent=5, descent=2)
    font.add("A", (".#.", "#.#", "###", "#.#", "#.#", "...", "..."))
    font.add("g", ("...", "###", "#.#", "#.#", "###", "..#", "##."))
    font.add("!", ("#", "#", "#", ".", "#", ".", "."))
    return font


def test_glyphs_must_match_the_font_height():
    font = BitmapFont("Test", ascent=5, descent=2)
    with pytest.raises(FontError, match="rows"):
        font.add("x", ("#",) * 6)
    with pytest.raises(FontError, match="lengths"):
        font.add("x", ("#", "##", "#", "#", "#", "#", "#"))


def test_render_advances_by_width_plus_spacing():
    img = small_font().render("A!A")
    assert img.size == (3 + 1 + 1 + 1 + 3 + 1, 7)
    assert img.getpixel((1, 0))[3] == 255 and img.getpixel((0, 0))[3] == 0
    assert img.getpixel((4, 4))[3] == 255
    with pytest.raises(FontError, match="no glyph"):
        small_font().render("B")


def test_a_glyph_can_override_the_spacing():
    font = small_font()
    font.add("-", ("...", "...", "###", "...", "...", "...", "..."), spacing=0)
    assert font.advance("-") == 3 and font.advance("A") == 4
    img = font.render("--")
    assert img.size == (6, 7)
    assert all(img.getpixel((x, 2))[3] == 255 for x in range(6)), "joined glyphs touch"
    with pytest.raises(FontError, match="spacing"):
        font.add("x", ("#",) * 7, spacing=-1)


def test_ttf_keeps_empty_columns_on_the_left(tmp_path):
    from fontTools.ttLib import TTFont

    font = small_font()
    font.add("|", (".#", ".#", ".#", ".#", ".#", "..", ".."), spacing=0)
    path = build_ttf(font, tmp_path / "test.ttf")
    tt = TTFont(str(path))
    advance, lsb = tt["hmtx"]["uni007C"]
    assert (advance, lsb) == (2 * 128, 128)
    assert tt["glyf"]["uni007C"].xMin == lsb


def test_ttf_rasterizes_back_to_the_same_pixels(tmp_path):
    font = small_font()
    path = build_ttf(font, tmp_path / "test.ttf")
    ttf = ImageFont.truetype(str(path), font.em)
    for text in ("A", "g", "A!g"):
        expected = font.render(text)
        canvas = Image.new("L", expected.size, 0)
        ImageDraw.Draw(canvas).text((0, 0), text, font=ttf, fill=255, anchor="la")
        got = [canvas.getpixel((x, y)) for y in range(expected.height) for x in range(expected.width)]
        want = [expected.getpixel((x, y))[3] for y in range(expected.height) for x in range(expected.width)]
        assert got == want, text


def test_ttf_maps_characters_and_metrics(tmp_path):
    from fontTools.ttLib import TTFont
    ttf = TTFont(str(build_ttf(small_font(), tmp_path / "test.ttf", units_per_pixel=100)))
    cmap = ttf.getBestCmap()
    assert {ord("A"), ord("g"), ord("!"), ord(" ")} <= set(cmap)
    assert ttf["head"].unitsPerEm == 700
    assert ttf["hmtx"][cmap[ord("A")]][0] == 400
    assert ttf["hhea"].ascent == 500 and ttf["hhea"].descent == -200
