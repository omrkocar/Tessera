import pytest
from PIL import Image

from conftest import BLUE, GREEN, RED, solid
from tessera import preview
from tessera.pack import Frame, PackError, pack, slice_grid


def test_equal_frames_pack_on_a_grid_in_order():
    frames = [Frame(f"f{i}", solid((16, 16), c)) for i, c in enumerate([RED, GREEN, BLUE])]
    sheet = pack(frames, padding=1, columns=2)
    assert sheet.image.size == (33, 33)
    assert [(r.name, r.x, r.y) for r in sheet.sprites] == [("f0", 0, 0), ("f1", 17, 0), ("f2", 0, 17)]
    assert sheet.image.getpixel((17, 0)) == GREEN
    assert sheet.image.getpixel((16, 0)) == (0, 0, 0, 0)  # padding stays empty


def test_mixed_sizes_use_shelves_and_keep_caller_order():
    frames = [Frame("small", solid((8, 8), RED)), Frame("tall", solid((16, 32), GREEN)),
              Frame("wide", solid((32, 16), BLUE))]
    sheet = pack(frames, max_width=48)
    assert [r.name for r in sheet.sprites] == ["small", "tall", "wide"]
    rects = {r.name: r for r in sheet.sprites}
    for name, rect in rects.items():
        color = {"small": RED, "tall": GREEN, "wide": BLUE}[name]
        assert sheet.image.getpixel((rect.x, rect.y)) == color
        assert sheet.image.getpixel((rect.x + rect.width - 1, rect.y + rect.height - 1)) == color
    # no overlaps
    boxes = list(rects.values())
    for i, a in enumerate(boxes):
        for b in boxes[i + 1:]:
            assert (a.x + a.width <= b.x or b.x + b.width <= a.x
                    or a.y + a.height <= b.y or b.y + b.height <= a.y)


def test_pack_rejects_bad_input():
    with pytest.raises(PackError):
        pack([])
    with pytest.raises(PackError, match="unique"):
        pack([Frame("a", solid((4, 4), RED)), Frame("a", solid((4, 4), RED))])
    with pytest.raises(PackError, match="max_width"):
        pack([Frame("a", solid((64, 4), RED)), Frame("b", solid((4, 4), RED))], max_width=32)


def test_slice_grid_skips_empty_cells():
    image = Image.new("RGBA", (48, 16))
    image.paste(solid((16, 16), RED), (0, 0))
    image.paste(solid((16, 16), BLUE), (32, 0))
    frames = slice_grid(image, 16, 16, "walk")
    assert [f.name for f in frames] == ["walk_0", "walk_1"]
    assert frames[1].image.getpixel((0, 0)) == BLUE
    with pytest.raises(PackError):
        slice_grid(image, 10, 16, "x")


def test_upscale_is_exact_nearest_neighbor():
    image = Image.new("RGBA", (2, 1))
    image.putpixel((0, 0), RED)
    image.putpixel((1, 0), BLUE)
    big = preview.upscale(image, 8)
    assert big.size == (16, 8)
    colors = {big.getpixel((x, y)) for x in range(8) for y in range(8)}
    assert colors == {RED}  # no blended edge pixels
    assert big.getpixel((8, 0)) == BLUE


def test_tiled_repeats_and_strip_orders_frames():
    image = solid((4, 4), RED)
    assert preview.tiled(image, 3, 2).size == (12, 8)
    frames = [solid((4, 4), RED), solid((4, 4), BLUE)]
    strip = preview.strip(frames, gutter=1)
    assert strip.size == (11, 6)
    assert strip.getpixel((1, 1)) == RED and strip.getpixel((6, 1)) == BLUE


def test_checker_backdrop_and_grid():
    assert preview.backdrop((16, 16), None, cell=8).getpixel((8, 0)) == preview.CHECKER_DARK
    grid = preview.draw_grid(solid((32, 32), (0, 0, 0, 255)), 16, (255, 255, 255, 255))
    assert grid.getpixel((16, 5)) == (255, 255, 255, 255)
    assert grid.getpixel((15, 5)) == (0, 0, 0, 255)


def test_gif_preview(tmp_path):
    path = tmp_path / "a.gif"
    preview.save_gif([solid((4, 4), RED), solid((4, 4), BLUE)], path, 4, 100, None)
    with Image.open(path) as gif:
        assert gif.n_frames == 2 and gif.size == (16, 16)
