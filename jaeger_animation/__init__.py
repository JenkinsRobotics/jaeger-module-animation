"""jaeger_animation — the universal animation engine for the Jaeger ecosystem.

Decodes assets and runs procedural scenes into RGBA frames, publishes
them on the bus, and knows nothing about displays, characters, or
personas.  Pins JaegerOS only — never JaegerAI — so a robot body can
have a face with no AI product installed.

    from jaeger_animation import make_animation_node
    node = make_animation_node(bus, {"width": 64, "height": 64})

Or without a bus at all, to check the engine renders:

    python -m jaeger_animation.play face.gif --headless

Origin: the engine was ported from Mochi (Apache-2.0), where it grew up
as ``nodes/media`` + ``nodes/animation``.  See ``docs/DESIGN.md`` for
what came across and what was deliberately left behind.
"""

from __future__ import annotations

__version__ = "0.2.0"

from .base import AnimationAdapter
from .config import AnimationConfig
from .frames import FrameBuffer
from .node import AnimationNode, make_animation_node
from .tools import TOOLS, play_animation, play_media, stop_animation

__all__ = [
    "AnimationAdapter",
    "AnimationConfig",
    "AnimationNode",
    "FrameBuffer",
    "TOOLS",
    "make_animation_node",
    "play_animation",
    "play_media",
    "stop_animation",
    "__version__",
]
