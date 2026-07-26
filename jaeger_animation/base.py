"""AnimationAdapter — the contract every adapter implements.

One tiny Protocol, three methods.  An adapter turns *some asset format*
into :class:`~jaeger_animation.frames.FrameBuffer` objects; the node
knows nothing else about it.  That is the whole extension point: a new
format is a new adapter, and neither the node nor JaegerOS changes.

``skill_id`` / ``level`` are descriptive metadata carried from the
adapters' origin in Mochi.  **Nothing in this package reads them** — the
skill tree is a product concept and lives in whatever consumes this
module.  They are kept because authoring tools find them useful, and
removing them would break nothing but tell future readers less.
"""

from __future__ import annotations

from typing import Protocol

from .frames import FrameBuffer

__all__ = ["AnimationAdapter", "FrameBuffer"]


class AnimationAdapter(Protocol):
    """Render an animation asset frame-by-frame.

    Implementations must be safe to ``open()`` repeatedly — switching
    assets re-opens rather than requiring a fresh instance.
    """

    skill_id: str
    level: int

    def open(self, asset_path: str, *, width: int, height: int,
             params: dict) -> None:
        """Prepare to render ``asset_path`` at ``width`` x ``height``.

        ``params`` is adapter-specific (e.g. ``{"loop": True,
        "fit": "contain"}``).  Idempotent on the same asset.

        The node passes geometry in at open() rather than resizing
        afterwards, so an adapter can decode straight to the target
        size — the difference between a 720p GIF and a 64x64 LED matrix
        is handled once, by the decoder, not per frame.
        """
        ...

    def close(self) -> None:
        """Release decoded resources.  Idempotent."""
        ...

    def next_frame(self, t: float) -> FrameBuffer | None:
        """Render the frame for time ``t`` (seconds since clip start).

        Returns ``None`` when a one-shot clip is complete.  Looping
        adapters never return ``None`` until :meth:`close` is called.
        """
        ...
