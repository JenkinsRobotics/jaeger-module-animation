"""Agentic I/O — the same capability, shaped for a model.

A module exposes two surfaces over one engine.  The **topics** serve any
consumer: publish an ``AnimationCommand`` and frames come back, exactly
as a plain Python project or a ROS-style control loop would want.  The
**tools** here serve an *agent*: named, described, coarse-grained, with
results phrased for a language model rather than a control loop.

The same split ships in ``kokoro_tts`` (``text_to_speech``) and
``whisper_stt`` (``listen``).  You can drive ``/act/speech`` directly; an
agent calls the tool.

**Persona-free, deliberately.**  These tools are the *mechanism* — "play
this asset through this adapter".  They are not
``set_avatar_state(emotion="happy")``, which needs a character's
emotion→asset table and therefore belongs to whatever consumes this
module.  Mechanism here, policy there.
"""

from __future__ import annotations

import uuid
from typing import Any

from jaeger_os.transport import topics

from .adapters import ADAPTERS

_ACK_TIMEOUT_S = 5.0


def _bus() -> Any:
    """The host's bus.  Resolved at call time, not import time — a tool
    module must not force a runtime to exist just to be imported."""
    from jaeger_os.nodes.runtime import get_bus
    return get_bus()


def play_animation(
    asset_path: str = "",
    adapter: str = "",
    duration_ms: int = 0,
    width: int = 0,
    height: int = 0,
    wait: bool = False,
) -> dict[str, Any]:
    """Play an animation asset on the face.

    Args:
      asset_path: file to play — an image, gif, sprite sheet, bitmap,
                  video, or a procedural MScript scene.
      adapter:    one of image/bitmap/sprite/gif/video/math. Leave blank
                  to choose by file extension.
      duration_ms: stop after this long. 0 = play to natural end
                  (an image holds; a gif runs one loop).
      width/height: render size. 0 = the node's configured geometry.
      wait:       block until the clip finishes. Default false — the
                  agent keeps moving while the face plays.

    Returns:
      ``{"ok": bool, "asset": str, "adapter": str, "reason": str|None}``
    """
    asset = (asset_path or "").strip()
    if not asset:
        return {"ok": False, "reason": "asset_path required"}
    key = (adapter or "").strip()
    if key and key not in ADAPTERS:
        return {
            "ok": False,
            "asset": asset,
            "reason": f"unknown adapter {key!r}; "
                      f"choose from {sorted(ADAPTERS)}",
        }

    params: dict[str, Any] = {}
    if width:
        params["width"] = int(width)
    if height:
        params["height"] = int(height)

    cmd = topics.AnimationCommand(
        adapter=key or "image",
        asset_path=asset,
        duration_ms=int(duration_ms),
        params=params,
        correlation_id=uuid.uuid4().hex,
    )
    try:
        bus = _bus()
        if wait:
            ack = bus.request(
                cmd, topics.SENSE_ANIMATION_STATE, timeout_s=_ACK_TIMEOUT_S)
            if ack is None:
                return {"ok": False, "asset": asset,
                        "reason": "no acknowledgement from the animation node"}
        else:
            bus.publish(cmd)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "asset": asset,
                "reason": f"{type(exc).__name__}: {exc}"}
    return {"ok": True, "asset": asset, "adapter": key or "image"}


def stop_animation() -> dict[str, Any]:
    """Stop whatever the face is currently playing.

    Returns:
      ``{"ok": bool, "reason": str|None}``
    """
    try:
        _bus().publish(topics.AnimationStop())
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "reason": f"{type(exc).__name__}: {exc}"}
    return {"ok": True}


def play_media(path: str = "", loop: bool = False) -> dict[str, Any]:
    """Play a media file (image, gif or video) as media rather than as
    the face.

    Frames go out on the media topic, so a renderer showing the face is
    not interrupted by a movie.

    Returns:
      ``{"ok": bool, "path": str, "reason": str|None}``
    """
    target = (path or "").strip()
    if not target:
        return {"ok": False, "reason": "path required"}
    try:
        _bus().publish(topics.MediaCommand(path=target, loop=bool(loop)))
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "path": target,
                "reason": f"{type(exc).__name__}: {exc}"}
    return {"ok": True, "path": target}


#: Declared in module.yaml's ``tools:``. Kept here so the manifest and
#: the implementations cannot drift — the module contract test asserts
#: these are exactly what module.yaml declares.
TOOLS = {
    "play_animation": play_animation,
    "stop_animation": stop_animation,
    "play_media": play_media,
}

__all__ = ["play_animation", "stop_animation", "play_media", "TOOLS"]
