"""SpriteAdapter — L2 SPRITE animation level.

Crops a single sprite from a sprite sheet image and centres it on
the canvas.  Frame sequencing (eye animations, mouth shapes through
time) is the timeline runner's job — each Timeline clip carries
one SpriteCommand with its own source rect.

Architecture vendored from Mochi
─────────────────────────────────
Mirrors Mochi's SpriteHandler (Apache 2.0; see
``dev/docs/library_review/mochi_demo.md``).  Same NumPy-based blit;
swapped RGB output for RGBA8 + JROS Protocol surface.

Skill tree
──────────
``skill_id = "animation.sprite"``, ``level = 2``.  Prerequisite for
this level is mastering at least one L1 STATIC adapter
(``animation.image`` OR ``animation.bitmap``).  Mastering this
unlocks ``animation.gif`` (L3).
"""

from __future__ import annotations

import numpy as np
from PIL import Image

from ..frames import FrameBuffer


class SpriteAdapter:
    """Crop one sprite from a sheet and emit it as a held frame."""

    skill_id: str = "animation.sprite"
    level: int = 2

    def __init__(self) -> None:
        self._buffer: bytes = b""
        self._width: int = 0
        self._height: int = 0
        self._emitted: bool = False

    # ── Protocol surface ──────────────────────────────────────────

    def open(self, asset_path: str, *, width: int, height: int,
             params: dict) -> None:
        """Load the sheet, crop the named source rect, centre on the
        target canvas, cache as RGBA8.

        ``params`` — two ways to say which sprite, pick one:

          ``src``    (x, y, w, h) crop on the sheet. Accepts list/tuple
                     or a comma-separated string ("0,0,32,32") for
                     MScript-compile compatibility.
          ``cell``   integer index into a uniform grid, with ``grid``
                     = (cols, rows). Row-major: cell 0 is top-left,
                     cell ``cols`` is the start of row 1.

        ``cell``/``grid`` exists because a caller should not have to do
        pixel arithmetic to pick frame 12 of an evenly-cut sheet — which
        is what almost every real sprite sheet is. ``src`` stays for
        irregular atlases where cells are not uniform.

          ``bg_rgb``  (r, g, b) canvas background; default black
        """
        p = dict(params or {})
        self._width = max(1, int(width))
        self._height = max(1, int(height))
        bg_rgb = tuple(p.get("bg_rgb", (0, 0, 0)))
        src_rect = _coerce_src(p.get("src"))
        if src_rect is None and p.get("cell") is not None:
            with Image.open(asset_path) as probe:
                sheet_w, sheet_h = probe.size
            src_rect = _cell_rect(
                p.get("cell"), p.get("grid"), sheet_w, sheet_h)
        if src_rect is None:
            raise ValueError(
                f"SpriteAdapter needs params['src'] = (x, y, w, h) or "
                f"params['cell'] with params['grid'] = (cols, rows); "
                f"got src={p.get('src')!r} cell={p.get('cell')!r}"
            )
        with Image.open(asset_path) as sheet:
            sx, sy, sw, sh = src_rect
            cropped = sheet.crop((sx, sy, sx + sw, sy + sh)).convert("RGBA")
        self._buffer = _composite_centred(
            cropped, self._width, self._height, bg_rgb,
        )
        self._emitted = False

    def close(self) -> None:
        self._buffer = b""
        self._emitted = False

    def next_frame(self, t: float) -> FrameBuffer | None:
        if not self._buffer or self._emitted:
            return None
        self._emitted = True
        return FrameBuffer(
            width=self._width,
            height=self._height,
            data=self._buffer,
            duration_ms=0,
            is_final=True,
        )


# ── helpers ───────────────────────────────────────────────────────

def _cell_rect(cell, grid, sheet_w: int, sheet_h: int,
               ) -> tuple[int, int, int, int]:
    """Row-major cell index on a uniform grid -> (x, y, w, h).

    Raises rather than clamping an out-of-range index: silently showing
    the wrong face is worse than a clear error naming the bounds.
    """
    if grid is None:
        raise ValueError("params['cell'] needs params['grid'] = (cols, rows)")
    try:
        cols, rows = (int(v) for v in grid)
    except Exception as exc:  # noqa: BLE001
        raise ValueError(
            f"params['grid'] must be (cols, rows); got {grid!r}") from exc
    if cols < 1 or rows < 1:
        raise ValueError(f"params['grid'] must be positive; got {grid!r}")
    idx = int(cell)
    if not 0 <= idx < cols * rows:
        raise ValueError(
            f"cell {idx} out of range for a {cols}x{rows} grid "
            f"({cols * rows} cells)")
    cw, ch = sheet_w // cols, sheet_h // rows
    return ((idx % cols) * cw, (idx // cols) * ch, cw, ch)


def _coerce_src(value) -> tuple[int, int, int, int] | None:
    """Accept (x, y, w, h) as list/tuple/string."""
    if value is None:
        return None
    if isinstance(value, str):
        try:
            parts = [int(s.strip()) for s in value.split(",")]
        except (ValueError, AttributeError):
            return None
        if len(parts) != 4:
            return None
        return (parts[0], parts[1], parts[2], parts[3])
    if isinstance(value, (list, tuple)) and len(value) == 4:
        return (int(value[0]), int(value[1]),
                int(value[2]), int(value[3]))
    return None


def _composite_centred(
    sprite: Image.Image,
    canvas_w: int, canvas_h: int,
    bg_rgb: tuple[int, int, int],
) -> bytes:
    canvas = Image.new(
        "RGBA",
        (canvas_w, canvas_h),
        (bg_rgb[0], bg_rgb[1], bg_rgb[2], 255),
    )
    sx = (canvas_w - sprite.width) // 2
    sy = (canvas_h - sprite.height) // 2
    canvas.paste(sprite, (sx, sy), sprite)
    return canvas.tobytes()
