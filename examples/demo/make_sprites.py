"""Draws the demo sprites: a 16x16 crate with 1px detail (a blur shows at once)
and a 4-frame blinking gem strip. Run: python examples/demo/make_sprites.py"""

from pathlib import Path

from PIL import Image

HERE = Path(__file__).parent
DARK, BROWN, TAN, LIGHT = (0x1d, 0x2b, 0x53), (0xab, 0x52, 0x36), (0xff, 0xa3, 0x00), (0xff, 0xf1, 0xe8)
GEM = [(0x29, 0xad, 0xff), (0x83, 0x76, 0x9c), (0x00, 0xe4, 0x36), (0xff, 0x00, 0x4d)]


def crate() -> Image.Image:
    image = Image.new("RGBA", (16, 16), (0, 0, 0, 0))
    px = image.load()
    for y in range(16):
        for x in range(16):
            edge = x in (0, 15) or y in (0, 15)
            diagonal = x == y or x == 15 - y
            if edge:
                color = DARK
            elif x in (1, 14) or y in (1, 14) or diagonal:
                color = TAN
            else:
                color = BROWN
            px[x, y] = (*color, 255)
    for x, y in ((2, 2), (13, 2), (2, 13), (13, 13)):  # single-pixel nails
        px[x, y] = (*LIGHT, 255)
    return image


def gem_strip() -> Image.Image:
    strip = Image.new("RGBA", (64, 16), (0, 0, 0, 0))
    px = strip.load()
    for frame, color in enumerate(GEM):
        ox = frame * 16
        for y in range(4, 12):
            half = 4 - abs(y - 7.5) + 0.5
            for x in range(int(8 - half), int(8 + half)):
                px[ox + x, y] = (*color, 255)
        px[ox + 6, 6] = (*LIGHT, 255)
    return strip


if __name__ == "__main__":
    out = HERE / "sprites"
    out.mkdir(exist_ok=True)
    crate().save(out / "crate.png")
    gem_strip().save(out / "gem_blink.png")
    print(f"wrote {out}")
