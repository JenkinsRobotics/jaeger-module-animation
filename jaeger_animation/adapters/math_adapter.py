"""MathAdapter — L4 procedural animation level.

Dynamically loads a Python file that defines a :class:`MathScript`
subclass; delegates rendering to it.  This is how Mochi-style faces
(eyes blinking, mouth shapes) get authored — operator writes a small
class that draws into an RGB numpy buffer, the adapter wraps it for
the JROS Protocol + RGBA8 output.

Architecture vendored from Mochi
─────────────────────────────────
Distilled from Mochi's MathHandler.  Same importlib-based plug-in
discovery; same delegation pattern.  Two changes for JROS:

  1. Scripts subclass JROS's :class:`MathScript` (a Protocol-ish
     base) instead of Mochi's Animation(ABC) — keeps the contract
     minimal.
  2. Scripts draw RGB (3 channels); the adapter converts to RGBA8
     before emitting the FrameBuffer.

Apache 2.0; see ``dev/docs/library_review/mochi_demo.md``.

Skill tree
──────────
``skill_id = "animation.math"``, ``level = 4``.  Procedural is the
gateway to L5/L6 — once an operator's writing math scripts they're
ready for rigged + generative.

Security note
─────────────
This adapter executes arbitrary Python.  Production use should
restrict ``asset_path`` to a sandbox (e.g.,
``<instance>/avatar/scripts/``).  0.5.x followup wires this through
``mochi.agent.tools._common._resolve_under``; the standalone
adapter trusts its caller for now.
"""

from __future__ import annotations

import contextlib
import importlib
import importlib.util
import os
import sys
from typing import Any, Callable

import numpy as np
from PIL import Image

from ..frames import FrameBuffer


class MathScript:
    """Base contract for operator-authored procedural animations.

    Subclasses MUST implement :meth:`render_into`; everything else
    has sensible defaults.

      def render_into(self, t: float, frame_rgb) -> None:
          # frame_rgb is a NumPy array of shape (h, w, 3), uint8.
          # Mutate it in place.

    Optional hooks:
      :meth:`on_enter` runs once when the clip starts (params live here)
      :meth:`on_event` runs when a Timeline clip carries an event tag
    """

    # Default runtime params — present on every MathScript so the
    # AnimationNode's set_runtime_param can update them without
    # the script having to opt in.  Subclasses can override
    # initial values in on_enter.
    amplitude_param: float = 0.0

    def __init__(self, width: int, height: int) -> None:
        self.width = width
        self.height = height

    def on_enter(self, **kwargs: Any) -> None:
        """Optional setup hook — runs once when the clip starts.
        Override to read params + initialise per-clip state."""

    def on_event(self, event: str, **kwargs: Any) -> None:
        """Optional event hook — Timeline clips can carry named events
        (e.g. "blink_now") that the script reacts to.  Default
        ignores."""

    def render_into(self, t: float, frame_rgb: np.ndarray) -> None:
        """REQUIRED: draw the frame at time ``t`` (seconds since the
        clip started) into ``frame_rgb`` (shape (h, w, 3), uint8).
        Must mutate the array in place."""
        raise NotImplementedError


class MathAdapter:
    """Run an operator-authored procedural animation."""

    skill_id: str = "animation.math"
    level: int = 4

    def __init__(self) -> None:
        self._script: MathScript | None = None
        self._rgb: Any = None      # reused render buffer
        self._width: int = 0
        self._height: int = 0
        self._start_t: float | None = None
        self._fps: float = 30.0
        self._duration_ms_per_frame: int = int(round(1000.0 / 30.0))

    # ── Protocol surface ──────────────────────────────────────────

    def open(self, asset_path: str, *, width: int, height: int,
             params: dict) -> None:
        """Load the Python file, instantiate the MathScript subclass.

        ``params``:
          ``fps``           target frame rate (default 30)
          everything else   passed verbatim to ``script.on_enter()``
        """
        p = dict(params or {})
        self._fps = float(p.pop("fps", 30.0))
        self._duration_ms_per_frame = max(
            1, int(round(1000.0 / max(0.1, self._fps))),
        )
        self._width = max(1, int(width))
        self._height = max(1, int(height))
        cls = _load_math_script_class(asset_path)
        if cls is None:
            raise ValueError(
                f"no MathScript subclass found in {asset_path!r}"
            )
        self._script = cls(self._width, self._height)
        try:
            self._script.on_enter(**p)
        except Exception:
            # If on_enter raises, drop the script so next_frame
            # returns None — the node logs it via its normal error
            # path.
            self._script = None
            raise
        self._start_t = None

    def set_runtime_param(self, key: str, value: Any) -> None:
        """Push a real-time parameter update to the running
        MathScript.  Lip-sync uses this to feed amplitude from
        :class:`mochi.transport.topics.TtsChunk` events into the script
        between frames.

        The script reads the value at its next ``render_into``
        call.  No-op if the script isn't open.
        """
        if self._script is None:
            return
        # Map well-known runtime params to the conventional
        # attribute names MathScripts use.
        if key == "amplitude":
            setattr(self._script, "amplitude_param", float(value))
        else:
            setattr(self._script, f"{key}_param", value)

    def close(self) -> None:
        self._script = None
        self._start_t = None
        self._rgb = None

    def next_frame(self, t: float) -> FrameBuffer | None:
        if self._script is None:
            return None
        if self._start_t is None:
            self._start_t = t
        elapsed = max(0.0, t - self._start_t)
        # Scenes render RGB (they do np.frombuffer(buf).reshape(h, w, 3),
        # so the buffer must be contiguous). Reuse it rather than
        # allocating per frame — though measurement says the allocation
        # itself is nearly free; numpy recycles freed blocks.
        rgb = self._rgb
        if rgb is None or rgb.shape != (self._height, self._width, 3):
            rgb = self._rgb = np.zeros(
                (self._height, self._width, 3), dtype=np.uint8)
        else:
            rgb[...] = 0
        try:
            self._script.render_into(elapsed, rgb)
        except Exception as exc:  # noqa: BLE001
            # Drop the script so the node stops calling a broken scene
            # every frame, and RAISE once. Returning None silently was
            # indistinguishable from "clip ended", which is how a scene
            # that never rendered looked like one that finished.
            self._script = None
            raise RuntimeError(
                f"scene render failed at t={elapsed:.3f}s: "
                f"{type(exc).__name__}: {exc}"
            ) from exc
        # RGB -> RGBA through PIL, which is 5.6x faster than numpy's
        # `rgba[..., :3] = rgb` (0.125 ms vs 0.701 ms on a 480x320
        # frame). numpy has to scatter 3 bytes out of every 4, which is
        # element-wise; PIL does it in one C loop. Measured, byte-
        # identical output, and PIL is already a hard dependency.
        #
        # That one line WAS 88% of the cost of a procedural frame.
        data = Image.fromarray(rgb, "RGB").convert("RGBA").tobytes()
        return FrameBuffer(
            width=self._width,
            height=self._height,
            data=data,
            duration_ms=self._duration_ms_per_frame,
            is_final=False,
        )


# ── helpers ───────────────────────────────────────────────────────

#: Package names existing scenes import the animation base class from.
#: Scene files are CONTENT, authored against whichever tree they grew up
#: in — Mochi wrote ``plugin_core.mochi_animations``, JaegerAI wrote
#: ``mscript.mochi_animations``, and this module holds the same code at
#: ``jaeger_animation.procedural``. Rather than rewrite every scene (and
#: break them for the projects they came from), the loader makes those
#: names resolve here for the duration of the import.
_SCENE_IMPORT_ALIASES = ("plugin_core", "mscript")


@contextlib.contextmanager
def _scene_import_aliases():
    """Temporarily expose ``jaeger_animation.procedural`` under the names
    scene files expect, then put ``sys.modules`` back exactly as it was.

    Scoped rather than installed at import time: making ``plugin_core``
    permanently importable would be this package quietly claiming a
    generic top-level name.
    """
    import jaeger_animation.procedural as _proc

    saved: dict[str, Any] = {}
    try:
        for alias in _SCENE_IMPORT_ALIASES:
            saved[alias] = sys.modules.get(alias)
            sys.modules[alias] = _proc
            for sub in ("mochi_animations", "gfx", "font", "color_utils",
                        "node_state"):
                key = f"{alias}.{sub}"
                saved[key] = sys.modules.get(key)
                try:
                    sys.modules[key] = importlib.import_module(
                        f"jaeger_animation.procedural.{sub}")
                except ImportError:
                    saved.pop(key, None)
        yield
    finally:
        for key, prior in saved.items():
            if prior is None:
                sys.modules.pop(key, None)
            else:
                sys.modules[key] = prior


def _load_math_script_class(asset_path: str):
    """Import the file at ``asset_path``; return the scene class it
    defines.

    Accepts BOTH lineages: a :class:`MathScript` subclass (this
    adapter's own base) or an :class:`Animation` subclass (what every
    real scene in Mochi and JaegerAI actually subclasses). Supporting
    only the first is why no scene rendered — the adapter defined a base
    class no content had ever heard of.
    """
    from ..procedural.mochi_animations import Animation

    module_name = f"_jaeger_scene_{os.path.splitext(os.path.basename(asset_path))[0]}"
    spec = importlib.util.spec_from_file_location(module_name, asset_path)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    with _scene_import_aliases():
        spec.loader.exec_module(module)
    for attr_name in dir(module):
        attr = getattr(module, attr_name)
        if not isinstance(attr, type):
            continue
        if issubclass(attr, MathScript) and attr is not MathScript:
            return attr
        if (issubclass(attr, Animation) and attr is not Animation
                and getattr(attr, "__abstractmethods__", None) == frozenset()):
            return attr
    return None
