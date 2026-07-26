"""Rebuild the `emotes` demo character atlas from its source screenshot.

The source (Mochi `assets/bmps/random_emotes.bmp`) is a 1280x456
SCREENSHOT: two 3x3 grids of faces plus two "Preview" window chrome
elements on a purple background. Shipping that as a sprite sheet would
mean every consumer hard-coding pixel offsets around UI furniture.

This extracts the 18 faces and writes a clean 9x2 atlas:

    row 0 — mouth OPEN   (talking)
    row 1 — mouth CLOSED (idle)
    column = emotion, in EMOTIONS order

Kept in the repo so the derivation is reproducible and the source is
attributable, not a mystery binary.

    python dev/tools/build_emotes_atlas.py [path/to/random_emotes.bmp]
"""

from __future__ import annotations

import pathlib
import sys

from PIL import Image

# Grid bounds detected from the source by background-difference masking
# (background is a flat purple, everything else is content).
GRID_OPEN = (34, 32, 426, 425)    # left 3x3  — mouths open
GRID_CLOSED = (675, 32, 1069, 425)  # right 3x3 — mouths closed

#: Emotion per cell, row-major within each 3x3 grid. Both grids carry the
#: same nine in the same order — that is what makes the sheet a talking
#: face rather than 18 loose pictures.
EMOTIONS = [
    "love", "shocked", "angry",
    "nervous", "frustrated", "crying",
    "happy", "unamused", "neutral",
]

CELL = 128
DEFAULT_SRC = "~/GITHUB/Mochi/mochi/assets/bmps/random_emotes.bmp"
OUT = pathlib.Path(__file__).resolve().parents[2] / \
    "jaeger_animation/assets/characters/emotes"


def _cells(img: Image.Image, box: tuple[int, int, int, int]) -> list[Image.Image]:
    x0, y0, x1, y1 = box
    w, h = (x1 - x0) / 3.0, (y1 - y0) / 3.0
    out = []
    for r in range(3):
        for c in range(3):
            crop = img.crop((round(x0 + c * w), round(y0 + r * h),
                             round(x0 + (c + 1) * w), round(y0 + (r + 1) * h)))
            # NEAREST: this is pixel art. Any smoothing filter destroys
            # exactly the thing that makes it readable at 64x64.
            out.append(crop.resize((CELL, CELL), Image.NEAREST))
    return out


def main(argv: list[str]) -> int:
    src_path = pathlib.Path(
        argv[1] if len(argv) > 1 else DEFAULT_SRC).expanduser()
    if not src_path.exists():
        print(f"source not found: {src_path}", file=sys.stderr)
        return 1

    src = Image.open(src_path).convert("RGBA")
    open_cells = _cells(src, GRID_OPEN)
    closed_cells = _cells(src, GRID_CLOSED)
    assert len(open_cells) == len(closed_cells) == len(EMOTIONS)

    sheet = Image.new("RGBA", (CELL * len(EMOTIONS), CELL * 2), (0, 0, 0, 0))
    for i, cell in enumerate(open_cells):
        sheet.paste(cell, (i * CELL, 0))
    for i, cell in enumerate(closed_cells):
        sheet.paste(cell, (i * CELL, CELL))

    OUT.mkdir(parents=True, exist_ok=True)
    dest = OUT / "emotes.png"
    sheet.save(dest)
    print(f"wrote {dest}  {sheet.size}  "
          f"{len(EMOTIONS)} emotions x 2 mouth states")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
