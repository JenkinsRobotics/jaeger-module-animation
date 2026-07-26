"""MScriptAdapter — play a motion script: a SEQUENCE of other assets.

Every other adapter turns one asset into frames. This one turns a
*script* into frames by driving the others:

    [Resources start]
    K[1]: 'assets/math/eyes.py'
    K[2]: 'assets/gifs/wave.gif'
    [Resources end]

    [Main start]
    MATH  K[1] D[3.0] FG[255,255,255]
    WAIT  D[0.5]
    MEDIA K[2] D[2.0]
    [Main end]

A character supplies motion scripts — or a caller sends a list of
commands — and the node executes the sequence. The script is the
character's, the execution is the engine's. That split is why this
belongs here rather than in a consumer: the sequence is *content*, and
playing content is what this module does.

Timing lives in :class:`MscriptScript` (vendored from Mochi): it tracks
a program counter and a wait-until clock, and `update(t)` returns only
the commands due by time ``t``. This adapter's job is to take those
commands, bind each to a real adapter, and keep pumping frames from
whichever is currently active.

**Composition, not a second engine.** It never decodes anything itself.
"""

from __future__ import annotations

import pathlib
from typing import Any

from ..frames import FrameBuffer

#: mscript command -> how to pick an adapter for its asset.
#: MATH always means a procedural scene; MEDIA/IMAGE/GIF/VIDEO are
#: whatever their file extension says.
_COMMAND_ADAPTERS = {
    "MATH": "math",
    "MSCRIPT": "math",
    "MEDIA": None,      # by extension
    "IMAGE": "image",
    "GIF": "gif",
    "VIDEO": "video",
    "SPRITE": "sprite",
    "BITMAP": "bitmap",
}

#: Commands that carry no asset and are safely ignored here — timing is
#: already applied by MscriptScript before we ever see them.
_TIMING_ONLY = {"WAIT", "CLEAR", "STOP", "END"}


class MScriptAdapter:
    """Render a `.mscript` by sequencing the adapters it references."""

    skill_id: str = "animation.mscript"
    level: int = 5

    def __init__(self) -> None:
        self._script: Any = None
        self._active: Any = None
        self._active_started: float = 0.0
        self._width = 0
        self._height = 0
        self._params: dict = {}
        self._asset_root: pathlib.Path | None = None
        self._start_t: float | None = None
        self._finished = False
        self._last: FrameBuffer | None = None

    # ── Protocol ─────────────────────────────────────────────────

    def open(self, asset_path: str, *, width: int, height: int,
             params: dict) -> None:
        """Parse the script.

        ``params``:
          ``asset_root``  where the script's relative resource paths
                          resolve from. Defaults to the script's own
                          grandparent (``assets/mscripts/x.mscript`` ->
                          the tree holding ``assets/``), which is the
                          layout every existing script was written
                          against. Pass it explicitly for packs laid out
                          any other way.
          everything else forwarded to each referenced adapter's open().
        """
        from ..procedural.mscript_engine import MscriptScript

        p = dict(params or {})
        self._width = max(1, int(width))
        self._height = max(1, int(height))
        root = p.pop("asset_root", None)
        script_path = pathlib.Path(asset_path).resolve()
        self._asset_root = (pathlib.Path(root).resolve() if root
                            else script_path.parent.parent.parent)
        self._params = p
        self._script = MscriptScript(str(script_path))
        self._active = None
        self._start_t = None
        self._finished = False
        self._last = None

    def close(self) -> None:
        self._close_active()
        self._script = None
        self._finished = False
        self._last = None

    def next_frame(self, t: float) -> FrameBuffer | None:
        if self._script is None:
            return None
        if self._start_t is None:
            self._start_t = t
        elapsed = max(0.0, t - self._start_t)

        # Drain whatever the script says is due by now. The LAST asset
        # command wins: a script that fires two clips in one tick meant
        # the second to replace the first, not to race it.
        try:
            commands = self._script.update(elapsed) or []
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(
                f"motion script failed at t={elapsed:.3f}s: "
                f"{type(exc).__name__}: {exc}") from exc

        pending = None
        for cmd in commands:
            name = str(getattr(cmd, "name", "")).upper()
            if name in _TIMING_ONLY:
                continue
            args = dict(getattr(cmd, "args", {}) or {})
            if args.get("asset_path"):
                pending = (name, args)
        if pending is not None:
            self._bind(*pending, elapsed=elapsed)

        if self._active is None:
            # Nothing bound yet, or the script has run out. Hold the
            # last frame rather than emitting None — None means "clip
            # over" to the node, and a script mid-WAIT is not over.
            if self._finished:
                return None
            return self._last

        frame = self._active.next_frame(elapsed - self._active_started)
        if frame is None:
            # The bound asset ended; hold its final frame until the
            # script says what comes next.
            self._close_active()
            return self._last
        self._last = frame
        return frame

    def set_runtime_param(self, key: str, value: Any) -> None:
        """Forward runtime params (lip-sync amplitude) to the active
        asset, if it accepts them."""
        setter = getattr(self._active, "set_runtime_param", None)
        if setter is not None:
            try:
                setter(key, value)
            except Exception:  # noqa: BLE001
                pass

    # ── internals ────────────────────────────────────────────────

    def _bind(self, command: str, args: dict, *, elapsed: float) -> None:
        """Swap the active adapter to the asset this command names."""
        from . import ADAPTERS, adapter_for_path

        raw = str(args.pop("asset_path"))
        path = pathlib.Path(raw)
        if not path.is_absolute() and self._asset_root is not None:
            path = self._asset_root / raw
        if not path.exists():
            raise FileNotFoundError(
                f"motion script references a missing asset: {raw} "
                f"(resolved to {path})")

        key = _COMMAND_ADAPTERS.get(command)
        if key is None:
            key = adapter_for_path(str(path))
        cls = ADAPTERS.get(key)
        if cls is None:
            raise ValueError(
                f"motion script command {command!r} needs adapter {key!r}, "
                f"which this engine does not have")

        self._close_active()
        adapter = cls()
        # Script args (FG, speed, ...) ride alongside the caller's, with
        # the script winning — it is the character's own intent.
        adapter.open(str(path), width=self._width, height=self._height,
                     params={**self._params, **_clean(args)})
        self._active = adapter
        self._active_started = elapsed

    def _close_active(self) -> None:
        if self._active is None:
            return
        try:
            self._active.close()
        except Exception:  # noqa: BLE001
            pass
        self._active = None


def _clean(args: dict) -> dict:
    """Drop mscript bookkeeping keys the adapters do not take."""
    return {k: v for k, v in args.items() if k not in {"K", "D"}}


__all__ = ["MScriptAdapter"]
