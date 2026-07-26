"""jaeger_animation.config — the module's settings-catalog slice.

Same shape as ``jaeger_kokoro_tts.config`` / ``jaeger_whisper_stt.config``:
a Pydantic model the host nests into its central ``Config`` under the key
``module.yaml`` names in ``config:``.

Import-cycle rule (house style, inherited from kokoro_tts/config.py):
this module must never import the host's ``schemas.py``.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class AnimationConfig(BaseModel):
    """Render settings for the animation engine.

    Geometry is a property of the display a face lands on, so it is
    per-instance rather than global — a manifest may override it per
    ``[[node]]``, which is how one unit drives two displays at different
    sizes from one module.
    """

    model_config = ConfigDict(extra="forbid")

    #: Render size when a command names none. 480x320 suits a desktop
    #: window; a 64x64 LED matrix sets its own in the manifest.
    width: int = Field(480, ge=1, le=8192)
    height: int = Field(320, ge=1, le=8192)

    #: Pacing fallback when an adapter reports no per-frame duration.
    #: Adapters that DO know (gif, video) always win — this only fills
    #: the gap for procedural scenes with no intrinsic rate.
    default_fps: int = Field(30, ge=1, le=240)

    #: How often render telemetry goes out on /sense/animation_stats.
    #: Never per frame: that would double the message rate of the thing
    #: it is measuring.
    stats_interval_s: float = Field(1.0, ge=0.1, le=60.0)

    #: How many play commands may queue before new ones are dropped
    #: (and counted in AnimationStats.frames_dropped). Small on purpose:
    #: a face should show the newest thing asked of it, not work through
    #: a backlog.
    queue_maxsize: int = Field(8, ge=1, le=256)


__all__ = ["AnimationConfig"]
