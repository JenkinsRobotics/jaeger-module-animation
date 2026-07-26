"""Procedural rendering — the MScript engine.

Ported from Mochi's ``nodes/animation/plugin_core/`` (Apache-2.0).  An
MScript scene is a small Python file that draws into a framebuffer at
whatever geometry it is handed, so one scene serves a desktop window and
a 64x64 LED matrix without a second asset.

``MathAdapter`` (in :mod:`jaeger_animation.adapters`) is the seam that
exposes this to the node — the engine here has no bus awareness.
"""

from __future__ import annotations

__all__ = ["mscript_engine", "gfx", "font", "color_utils", "node_state"]
