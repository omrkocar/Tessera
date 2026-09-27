# Tessera

A small pixel-art pipeline for 2D games: palette checks, previews, sprite-sheet
packing and engine export. It holds no style of its own. Each game supplies a
project config (palette, tile size, shading rules, output targets), so the
same tool serves any number of games.

## Install

Python 3.11+ and Pillow.

```
python -m pip install -e ".[dev]"
```

This puts a `tessera` command on the Python scripts path; `python -m tessera`
works everywhere.

## Project config

A project is a folder with a `tessera.toml`. Commands find it through
`--project` or by walking up from the current folder. Paths in the file are
relative to it. Unknown keys are errors, so typos never fall back to defaults.
`examples/demo/tessera.toml` shows every section:

| Section | Keys |
|---|---|
| `[project]` | `name` |
| `[palette]` | `file` (.hex or GIMP .gpl) or `colors` (list of hex), `max_colors`, `allow_partial_alpha` |
| `[grid]` | `tile_size`, `pixels_per_unit` (defaults to `tile_size`) |
| `[shading]` | `light_direction`, `outline` (none, dark, selective), `max_ramp` |
| `[preview]` | `scale`, `background` ("checker" or hex), `grid_color` |
| `[pack]` | `padding`, `max_width` |
| `[[outputs]]` | `target` (e.g. "unity"), `path`, `pivot`, plus target options |

## Commands

```
tessera info                                   # resolved config
tessera validate sprites/                      # exit 1 on any off-palette pixel
tessera preview tile.png --tile 3x3 --grid -o out/tile.png
tessera sheet sprites/ -o out/contact.png      # contact sheet, upscaled
tessera strip walk.png --slice 16x24 -o out/walk.gif --fps 8
tessera pack frames/*.png --name walk -o out/  # sheet + JSON rects
tessera export unity crate.png --pivot bottom  # into the configured folder
tessera export unity walk.png --slice 16x24    # one texture, many sprites
```

`export` validates the palette first and refuses to write off-palette art
(`--no-validate` skips it). One input exports as a single sprite; `--slice`
or several inputs pack into a multi-sprite texture.

## Unity target

Writes `<name>.png` and a matching `.png.meta`, so Unity imports it as pixel
art with no clicks: Sprite type, point filtering, no mipmaps, no compression,
the project's pixels per unit, a max texture size that never downsamples, and
the sprite slices with the chosen pivot. Re-exporting keeps the GUID and
derives sprite IDs from GUID and sprite name, so references in scenes and
prefabs survive as long as sprite names stay the same. Options in the
`[[outputs]]` entry: `physics_shape` (default true), `mesh` ("full" or
"tight", default "full").

Verified on Unity 6000.6: imported pixels match the source exactly, and an
8x camera render shows only palette colors (`docs/unity-check.png`).

## Adding a target

Subclass `tessera.exporters.Exporter`, set `target`, implement
`export(asset)`, decorate with `@register` and import the module in
`tessera/exporters/__init__.py`.

## Tests

```
python -m pytest
```

## License

Proprietary, all rights reserved. Private repository.
