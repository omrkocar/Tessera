import json

import pytest
from PIL import Image

from conftest import BLACK, RED
from tessera.config import load_config
from tessera.exporters import ExportError
from tessera.tileset import (BLOB_MASKS, CARDINAL_MASKS, DIRECTIONS, E, N, NE, S, W,
                             blob_inside, connected_tileset, export_tileset, mask_at,
                             random_tileset, reduce_blob, render_cells)

DEPTH = [3, 3, 3, 2, 2, 2, 3, 3, 4, 4, 3, 3, 3, 2, 3, 3]


def shape_image(mask, frame=0):
    image = Image.new("RGBA", (16, 16), (0, 0, 0, 0))
    for y in range(16):
        for x in range(16):
            if blob_inside(mask, 16, DEPTH, x, y):
                image.putpixel((x, y), RED)
    return image


def line_image(mask, frame=0):
    image = Image.new("RGBA", (16, 16), (0, 0, 0, 0))
    image.putpixel((mask % 16, 0), BLACK)
    return image


def test_mask_counts():
    assert len(BLOB_MASKS) == 47
    assert len(CARDINAL_MASKS) == 16


def test_diagonal_only_counts_between_two_cardinals():
    assert reduce_blob(NE) == 0
    assert reduce_blob(N | NE) == N
    assert reduce_blob(N | E | NE) == N | E | NE


def test_blob_edges_line_up_between_neighbors():
    cells = {(x, y) for x in range(4) for y in range(3)} | {(1, 3), (2, 3)}
    for x, y in cells:
        mask = mask_at(cells, x, y)
        for dx, dy in ((1, 0), (0, 1)):
            other = (x + dx, y + dy)
            if other not in cells:
                continue
            omask = mask_at(cells, *other)
            for t in range(16):
                if dx:   # our right column against their left column
                    a, b = blob_inside(mask, 16, DEPTH, 15, t), blob_inside(omask, 16, DEPTH, 0, t)
                else:    # our bottom row against their top row
                    a, b = blob_inside(mask, 16, DEPTH, t, 15), blob_inside(omask, 16, DEPTH, t, 0)
                assert a == b, (x, y, other, t)


def test_isolated_piece_is_closed_and_full_piece_is_full():
    lone = [[blob_inside(0, 16, DEPTH, x, y) for x in range(16)] for y in range(16)]
    assert not any(lone[0]) and not any(lone[15]) and lone[8][8]
    assert all(blob_inside(255, 16, DEPTH, x, y) for x in range(16) for y in range(16))


def test_rules_pick_the_piece_drawn_for_each_mask():
    tileset = connected_tileset("t", "blob", 16, shape_image)
    for mask in range(256):
        expected = shape_image(reduce_blob(mask))
        assert tileset.piece(mask).tobytes() == expected.tobytes()
    full = next(r for r in tileset.rules if r.frames == ["t_255"])
    assert sorted(full.this) == sorted(DIRECTIONS) and full.not_this == []
    top_edge = next(r for r in tileset.rules if r.frames == [f"t_{E | S | W}"])
    assert "N" in top_edge.not_this and "NE" not in top_edge.this + top_edge.not_this


def test_cardinal_rules_ignore_diagonals():
    tileset = connected_tileset("fence", "cardinal", 16, line_image, collider="grid")
    assert len(tileset.rules) == 16
    assert all(len(r.this) + len(r.not_this) == 4 for r in tileset.rules)
    assert tileset.piece(N | S | NE).tobytes() == line_image(N | S).tobytes()


def test_animated_pieces_are_named_by_frame():
    tileset = connected_tileset("water", "blob", 16, shape_image, frames=3, fps=4)
    assert tileset.rules[0].frames[0].endswith("_f0") and len(tileset.rules[0].frames) == 3
    assert len(tileset.images) == 47 * 3


def test_export_writes_texture_meta_and_rules(project_dir):
    project = load_config(project_dir)
    tileset = connected_tileset("path", "blob", 16, shape_image, preview_mask=255)
    written = export_tileset(project, tileset)
    names = sorted(p.name for p in written)
    assert names == ["path.png", "path.png.meta", "path.tileset.json"]
    rules = json.loads((project_dir / "unity_out" / "path.tileset.json").read_text(encoding="utf-8"))
    assert rules["layout"] == "blob" and rules["preview"] == "path_255" and len(rules["rules"]) == 47
    meta = (project_dir / "unity_out" / "path.png.meta").read_text(encoding="utf-8")
    assert "second: path_255" in meta


def test_export_refuses_off_palette_pieces(project_dir):
    project = load_config(project_dir)
    grey = Image.new("RGBA", (16, 16), (128, 128, 128, 255))
    with pytest.raises(ExportError, match="palette"):
        export_tileset(project, random_tileset("grass", [grey]))


def test_render_cells_paints_layers_in_order():
    ground = random_tileset("g", [Image.new("RGBA", (16, 16), BLACK)])
    over = connected_tileset("o", "blob", 16, shape_image)
    image = render_cells([(ground, {(0, 0), (1, 0)}), (over, {(0, 0)})], 2, 1)
    assert image.getpixel((8, 8)) == RED and image.getpixel((0, 0)) == BLACK
    assert image.getpixel((24, 8)) == BLACK
