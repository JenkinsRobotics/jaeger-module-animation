"""Adapters — one per asset format, all producing RGBA ``FrameBuffer``.

Ported from Mochi (Apache-2.0), which is where this engine grew up.
``image``/``gif``/``sprite``/``bitmap``/``video`` came from Mochi's
``nodes/media/decoders/``; ``math`` from ``nodes/animation/adapters/``.

Two families, one Protocol:

* **decoders** read a file — PNG, GIF, sprite sheet, bitmap, video.
* **procedural** compute pixels — ``MathAdapter`` runs a scene.
* **sequence** — ``MScriptAdapter`` plays a motion script by driving the
  others in turn. It decodes nothing itself; a character supplies the
  script and the engine executes it.

Procedural is the half that generalizes across geometry: a 720p GIF
cannot meaningfully render on a 24x8 LED strip, but a procedural scene
renders at whatever size it is asked for.  That is why both families
live in one engine.
"""

from __future__ import annotations

from .bitmap_adapter import BitmapAdapter
from .gif_adapter import GifAdapter
from .image_adapter import ImageAdapter
from .math_adapter import MathAdapter
from .mscript_adapter import MScriptAdapter
from .sprite_adapter import SpriteAdapter
from .video_adapter import VideoAdapter

__all__ = [
    "BitmapAdapter",
    "GifAdapter",
    "ImageAdapter",
    "MScriptAdapter",
    "MathAdapter",
    "SpriteAdapter",
    "VideoAdapter",
]


#: Asset extension -> adapter key.  Used by the node and the player to
#: pick a default when the caller does not name an adapter explicitly.
EXTENSION_MAP: dict[str, str] = {
    # NOTE: ".bmp" is an IMAGE, not `bitmap`. BitmapAdapter renders
    # 1-bit packed monochrome from a JSON payload (Adafruit-GFX style);
    # a .bmp file is a full-colour raster PIL reads directly. Routing
    # .bmp -> bitmap made it try to json.loads() binary and die on a
    # UnicodeDecodeError.
    ".png": "image", ".jpg": "image", ".jpeg": "image", ".webp": "image",
    ".bmp": "image", ".tif": "image", ".tiff": "image",
    ".json": "bitmap",
    ".gif": "gif",
    ".mp4": "video", ".mov": "video", ".mkv": "video", ".webm": "video",
    ".m4v": "video", ".avi": "video",
    ".py": "math",
    # A motion script is a SEQUENCE of the assets above, not a format of
    # its own — see mscript_adapter.
    ".mscript": "mscript",
}

#: Adapter key -> class.  The one place the key strings are bound to
#: implementations; the node registers from here so adding an adapter is
#: a one-line change in this file and nowhere else.
ADAPTERS: dict[str, type] = {
    "image": ImageAdapter,
    "bitmap": BitmapAdapter,
    "sprite": SpriteAdapter,
    "gif": GifAdapter,
    "video": VideoAdapter,
    "math": MathAdapter,
    "mscript": MScriptAdapter,
}


def adapter_for_path(path: str, *, default: str = "image") -> str:
    """Adapter key for ``path``'s extension.  Sprite sheets share PNG's
    extension, so they must be requested explicitly — there is no way to
    tell one from a plain image by filename alone."""
    import pathlib
    return EXTENSION_MAP.get(pathlib.Path(path).suffix.lower(), default)
