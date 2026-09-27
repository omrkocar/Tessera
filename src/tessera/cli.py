"""Command line: ``tessera <command> ...``. Run ``tessera -h`` for the list.

Every command finds the project config (tessera.toml) from ``--project`` or
by walking up from the current folder.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from PIL import Image

from tessera import __version__, preview
from tessera.config import PIVOTS, ConfigError, ProjectConfig, load_config
from tessera.exporters import ExportAsset, ExportError, create_exporter, targets
from tessera.pack import Frame, PackError, load_frames, pack, slice_grid
from tessera.palette import validate_image


class CliError(Exception):
    pass


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        project = load_config(Path(args.project) if args.project else Path.cwd())
        return args.run(project, args)
    except (CliError, ConfigError, PackError, ExportError, OSError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tessera", description="Pixel-art pipeline.")
    parser.add_argument("--version", action="version", version=f"tessera {__version__}")
    parser.add_argument("-p", "--project", help="tessera.toml or its folder (default: search upward)")
    commands = parser.add_subparsers(dest="command", required=True, metavar="command")

    info = commands.add_parser("info", help="show the resolved project config")
    info.set_defaults(run=cmd_info)

    validate = commands.add_parser("validate", help="reject off-palette pixels")
    validate.add_argument("inputs", nargs="+", help="PNG files or folders (searched recursively)")
    validate.set_defaults(run=cmd_validate)

    prev = commands.add_parser("preview", help="nearest-neighbor upscale of one image")
    prev.add_argument("input")
    prev.add_argument("-o", "--output", required=True)
    prev.add_argument("--scale", type=int, help="default: [preview] scale")
    prev.add_argument("--tile", metavar="COLSxROWS", help="repeat the image, e.g. 3x3, to check seams")
    prev.add_argument("--grid", action="store_true", help="draw the tile grid")
    prev.set_defaults(run=cmd_preview)

    sheet = commands.add_parser("sheet", help="contact sheet of many images, upscaled")
    sheet.add_argument("inputs", nargs="+")
    sheet.add_argument("-o", "--output", required=True)
    sheet.add_argument("--columns", type=int)
    sheet.add_argument("--scale", type=int)
    sheet.set_defaults(run=cmd_sheet)

    anim = commands.add_parser("strip", help="animation strip (.png) or animated preview (.gif)")
    anim.add_argument("inputs", nargs="+", help="frames in order, or one sheet with --slice")
    anim.add_argument("-o", "--output", required=True, help="ends in .png or .gif")
    anim.add_argument("--slice", metavar="WxH", help="cut a single input into WxH frames")
    anim.add_argument("--scale", type=int)
    anim.add_argument("--fps", type=float, default=8.0, help="gif only (default 8)")
    anim.set_defaults(run=cmd_strip)

    pk = commands.add_parser("pack", help="pack frames into a sheet + JSON metadata")
    pk.add_argument("inputs", nargs="+")
    pk.add_argument("--name", required=True)
    pk.add_argument("-o", "--output-dir", required=True)
    pk.add_argument("--columns", type=int)
    pk.add_argument("--slice", metavar="WxH", help="cut a single input into WxH frames first")
    pk.set_defaults(run=cmd_pack)

    export = commands.add_parser("export", help="validate, pack and write into an engine project")
    export.add_argument("target", choices=targets())
    export.add_argument("inputs", nargs="+", help="one image (whole sprite or --slice) or many frames")
    export.add_argument("--name", help="asset name (default: stem of the single input)")
    export.add_argument("--slice", metavar="WxH", help="cut a single input into WxH sprites")
    export.add_argument("--columns", type=int)
    export.add_argument("--pivot", choices=tuple(PIVOTS), help="default: the output's pivot")
    export.add_argument("--out", help="override the output folder from the config")
    export.add_argument("--no-validate", action="store_true", help="skip the palette check")
    export.set_defaults(run=cmd_export)
    return parser


# Commands ---------------------------------------------------------------

def cmd_info(project: ProjectConfig, args) -> int:
    print(f"project      {project.name}  ({project.root})")
    print(f"palette      {len(project.palette)} colors, partial alpha "
          f"{'allowed' if project.allow_partial_alpha else 'rejected'}")
    print(f"grid         {project.grid.tile_size}px tiles, {project.grid.pixels_per_unit} px/unit")
    print(f"shading      light {project.shading.light_direction}, outline {project.shading.outline}, "
          f"ramp <= {project.shading.max_ramp}")
    print(f"preview      x{project.preview.scale}")
    print(f"pack         padding {project.pack.padding}, max width {project.pack.max_width}")
    for output in project.outputs:
        print(f"output       {output.target} -> {output.path} (pivot {output.pivot})")
    return 0


def cmd_validate(project: ProjectConfig, args) -> int:
    files = expand_inputs(args.inputs)
    failed = 0
    for path in files:
        with Image.open(path) as image:
            report = validate_image(image, project.palette, project.allow_partial_alpha, str(path))
        print(report.describe())
        failed += not report.ok
    print(f"{len(files) - failed}/{len(files)} passed")
    return 1 if failed else 0


def cmd_preview(project: ProjectConfig, args) -> int:
    image = open_rgba(Path(args.input))
    scale = args.scale or project.preview.scale
    if args.tile:
        cols, rows = parse_size(args.tile, "--tile")
        image = preview.tiled(image, cols, rows)
    out = preview.upscale(image, scale)
    if args.grid:
        out = preview.draw_grid(out, project.grid.tile_size * scale, project.preview.grid_color)
    out = preview.flatten(out, project.preview.background, cell=scale * 2)
    save(out, Path(args.output))
    return 0


def cmd_sheet(project: ProjectConfig, args) -> int:
    images = [open_rgba(p) for p in expand_inputs(args.inputs)]
    scale = args.scale or project.preview.scale
    sheet = preview.contact_sheet(images, args.columns)
    out = preview.flatten(preview.upscale(sheet, scale), project.preview.background, cell=scale * 2)
    save(out, Path(args.output))
    return 0


def cmd_strip(project: ProjectConfig, args) -> int:
    frames = [f.image for f in read_frames(args.inputs, args.slice, "frame")]
    scale = args.scale or project.preview.scale
    output = Path(args.output)
    if output.suffix.lower() == ".gif":
        output.parent.mkdir(parents=True, exist_ok=True)
        preview.save_gif(frames, output, scale, round(1000 / args.fps), project.preview.background)
        print(f"wrote {output}")
    else:
        strip = preview.upscale(preview.strip(frames), scale)
        save(preview.flatten(strip, project.preview.background, cell=scale * 2), output)
    return 0


def cmd_pack(project: ProjectConfig, args) -> int:
    frames = read_frames(args.inputs, args.slice, args.name)
    sheet = pack(frames, project.pack.padding, args.columns, project.pack.max_width)
    folder = Path(args.output_dir)
    save(sheet.image, folder / f"{args.name}.png")
    meta = {
        "name": args.name,
        "size": list(sheet.image.size),
        "sprites": [{"name": r.name, "x": r.x, "y": r.y, "w": r.width, "h": r.height}
                    for r in sheet.sprites],
    }
    (folder / f"{args.name}.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {folder / (args.name + '.json')}")
    return 0


def cmd_export(project: ProjectConfig, args) -> int:
    paths = expand_inputs(args.inputs)
    if not args.no_validate:
        failures = []
        for path in paths:
            with Image.open(path) as image:
                report = validate_image(image, project.palette, project.allow_partial_alpha, str(path))
            if not report.ok:
                failures.append(report.describe())
        if failures:
            raise CliError("palette check failed (use --no-validate to skip):\n  " + "\n  ".join(failures))

    exporter = create_exporter(project, args.target, Path(args.out) if args.out else None)
    pivot = args.pivot or exporter.output.pivot
    if len(paths) == 1 and not args.slice:
        name = args.name or paths[0].stem
        asset = ExportAsset.whole(name, open_rgba(paths[0]), pivot)
    else:
        if len(paths) > 1 and not args.name:
            raise CliError("--name is required when exporting several frames")
        name = args.name or paths[0].stem
        frames = read_frames([str(p) for p in paths], args.slice, name)
        sheet = pack(frames, project.pack.padding, args.columns, project.pack.max_width)
        asset = ExportAsset(name, sheet.image, sheet.sprites, pivot)
    for path in exporter.export(asset):
        print(f"wrote {path}")
    return 0


# Helpers ----------------------------------------------------------------

def expand_inputs(inputs: list[str]) -> list[Path]:
    files: list[Path] = []
    for item in inputs:
        path = Path(item)
        if path.is_dir():
            files.extend(sorted(path.rglob("*.png")))
        elif path.is_file():
            files.append(path)
        else:
            raise CliError(f"no such file or folder: {item}")
    if not files:
        raise CliError("no PNG files found")
    return files


def read_frames(inputs: list[str], slice_size: str | None, prefix: str) -> list[Frame]:
    paths = expand_inputs(inputs)
    if slice_size:
        if len(paths) != 1:
            raise CliError("--slice takes exactly one input image")
        w, h = parse_size(slice_size, "--slice")
        return slice_grid(open_rgba(paths[0]), w, h, prefix)
    return load_frames(paths)


def parse_size(text: str, flag: str) -> tuple[int, int]:
    try:
        w, h = (int(v) for v in text.lower().split("x"))
    except ValueError:
        raise CliError(f"{flag} expects WxH, e.g. 16x16, got {text!r}") from None
    if w < 1 or h < 1:
        raise CliError(f"{flag} values must be positive")
    return w, h


def open_rgba(path: Path) -> Image.Image:
    with Image.open(path) as image:
        return image.convert("RGBA")


def save(image: Image.Image, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)
    print(f"wrote {path}")
