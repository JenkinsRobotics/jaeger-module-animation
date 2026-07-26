"""AnimationNode — decode/render an asset, publish frames on the bus.

    /act/animation      ─┐                    ┌─▶ /sense/media_frame
    /act/animation_stop ─┼─▶  AnimationNode  ─┼─▶ /sense/animation_state
    /act/media          ─┘                    └─▶ /sense/media_state

**The node's job ends at frames on a topic.**  It has no renderer, no
frame callback, no idea whether anything is listening.  A desktop window,
a web canvas, and a driver re-encoding for a 64x64 LED matrix all
subscribe the same way — which is the entire reason one engine can serve
a virtual companion and a physical robot without forking.

Two intents, one engine:

* ``/act/animation`` — play a named clip through a named adapter.  This
  is the face: an avatar expression, an eye state, a procedural scene.
* ``/act/media`` — play an arbitrary file, adapter chosen by extension.

Both decode through the same adapters and emit the same ``MediaFrame``.
They stay distinct because "make the face do this" and "play this movie"
are different intents to a consumer even when the pixels arrive
identically.

Threading: subscriber callbacks only enqueue.  All decoding happens in
``tick()`` on the node's own thread, because blocking the bus delivery
thread back-pressures every other subscriber on every other topic.

**Persona-free by construction.**  The vocabulary here is "play this
asset at this geometry", never "be happy".  Emotion-to-asset mapping is
character data owned by whatever consumes this module.
"""

from __future__ import annotations

import queue
import threading
import time
from typing import Any

from jaeger_os.nodes.base import Node
from jaeger_os.transport import Bus, topics

from .adapters import ADAPTERS, adapter_for_path
from .base import AnimationAdapter
from .frames import FrameBuffer

# Geometry the node renders at when a command names none.  Overridable
# per-instance from the manifest (see make_animation_node) because a
# face's size is a property of the display it lands on, not of the clip.
DEFAULT_WIDTH = 480
DEFAULT_HEIGHT = 320

# Frame pacing fallback when an adapter reports no per-frame duration.
_DEFAULT_FRAME_MS = 33  # ~30 fps


class AnimationNode(Node):
    """Render animation/media commands into frames on the bus."""

    def __init__(
        self,
        *,
        bus: Bus,
        width: int = DEFAULT_WIDTH,
        height: int = DEFAULT_HEIGHT,
        name: str = "animation",
        queue_maxsize: int = 8,
        install_signal_handlers: bool = False,
    ) -> None:
        super().__init__(
            bus=bus,
            name=name,
            install_signal_handlers=install_signal_handlers,
        )
        self._width = int(width)
        self._height = int(height)
        self._adapters: dict[str, AnimationAdapter] = {}
        self._active: AnimationAdapter | None = None
        self._active_key = ""
        self._active_asset = ""
        self._started_at = 0.0
        self._stop_clip = threading.Event()
        self._pending: "queue.Queue[tuple[str, str, int, dict]]" = queue.Queue(
            maxsize=queue_maxsize,
        )

    # ── adapter registration ─────────────────────────────────────

    def register_adapter(self, key: str, adapter: AnimationAdapter) -> None:
        """Bind ``key`` (as named in an AnimationCommand) to an adapter."""
        self._adapters[key] = adapter

    def register_default_adapters(self) -> None:
        """Register every adapter this module ships.

        Lives here rather than in a caller so that any construction path
        — a manifest factory, a test, a consumer building the node by
        hand — gets the same adapter table.  Adapters whose optional
        libraries are missing are skipped rather than failing the node:
        a missing video codec must not cost you a face.
        """
        for key, cls in ADAPTERS.items():
            try:
                self._adapters[key] = cls()
            except Exception as exc:  # noqa: BLE001
                self._log(f"adapter {key!r} unavailable: "
                          f"{type(exc).__name__}: {exc}")

    def known_adapters(self) -> tuple[str, ...]:
        return tuple(sorted(self._adapters))

    # ── lifecycle ────────────────────────────────────────────────

    def setup(self) -> None:
        self.bus.subscribe(topics.ACT_ANIMATION, self._on_animation)
        self.bus.subscribe(topics.ACT_ANIMATION_STOP, self._on_stop)
        self.bus.subscribe(topics.ACT_MEDIA, self._on_media)
        self._log(
            f"subscribed: {topics.ACT_ANIMATION}, "
            f"{topics.ACT_ANIMATION_STOP}, {topics.ACT_MEDIA} "
            f"@ {self._width}x{self._height}; "
            f"adapters={list(self.known_adapters())}"
        )

    def tick(self) -> None:
        try:
            key, asset, duration_ms, params = self._pending.get(timeout=0.1)
        except queue.Empty:
            return
        self._play(key, asset, duration_ms, params)

    def teardown(self) -> None:
        for topic, handler in (
            (topics.ACT_ANIMATION, self._on_animation),
            (topics.ACT_ANIMATION_STOP, self._on_stop),
            (topics.ACT_MEDIA, self._on_media),
        ):
            try:
                self.bus.unsubscribe(topic, handler)
            except Exception:  # noqa: BLE001
                pass
        self._close_active()

    def health(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "geometry": f"{self._width}x{self._height}",
            "adapters": list(self.known_adapters()),
            "playing": self._active_asset or None,
            "queue_depth": self._pending.qsize(),
        }

    # ── subscribers (enqueue only — never decode here) ───────────

    def _on_animation(self, msg: Any) -> None:
        params = dict(getattr(msg, "params", None) or {})
        self._enqueue(
            key=getattr(msg, "adapter", "") or "image",
            asset=getattr(msg, "asset_path", "") or "",
            duration_ms=int(getattr(msg, "duration_ms", 0) or 0),
            params=params,
        )

    def _on_media(self, msg: Any) -> None:
        path = getattr(msg, "path", "") or ""
        if not path:
            return
        self._enqueue(
            key=adapter_for_path(path),
            asset=path,
            duration_ms=0,
            params={"loop": bool(getattr(msg, "loop", True)), "_media": True},
        )

    def _on_stop(self, msg: Any) -> None:
        self._stop_clip.set()

    def _enqueue(self, *, key: str, asset: str, duration_ms: int,
                 params: dict) -> None:
        if not asset:
            return
        try:
            self._pending.put_nowait((key, asset, duration_ms, params))
        except queue.Full:
            self._log(f"queue full; dropped {key!r} clip {asset!r}")

    # ── playback ─────────────────────────────────────────────────

    def _play(self, key: str, asset: str, duration_ms: int,
              params: dict) -> None:
        is_media = bool(params.pop("_media", False))
        adapter = self._adapters.get(key)
        if adapter is None:
            self._log(f"unknown adapter {key!r}; skipping {asset!r}")
            self._publish_state(key, asset, "idle", is_media=is_media,
                                reason="unknown adapter")
            return

        if self._active is not None and self._active is not adapter:
            self._close_active()

        width = int(params.pop("width", self._width))
        height = int(params.pop("height", self._height))
        try:
            adapter.open(asset, width=width, height=height, params=params)
        except Exception as exc:  # noqa: BLE001
            # A bad file must never kill the node — the face just stays
            # as it was.
            self._log(f"open failed for {asset!r}: "
                      f"{type(exc).__name__}: {exc}")
            self._publish_state(key, asset, "idle", is_media=is_media,
                                reason=f"{type(exc).__name__}: {exc}")
            return

        self._active = adapter
        self._active_key = key
        self._active_asset = asset
        self._started_at = time.perf_counter()
        self._stop_clip.clear()
        self._publish_state(key, asset, "playing", is_media=is_media)

        try:
            self._stream(adapter, duration_ms, is_media=is_media)
        except Exception as exc:  # noqa: BLE001
            self._log(f"stream error on {asset!r}: "
                      f"{type(exc).__name__}: {exc}")

        self._close_active()
        self._publish_state(key, asset, "idle", is_media=is_media)

    def _stream(self, adapter: AnimationAdapter, duration_ms: int, *,
                is_media: bool) -> None:
        """Emit frames until the clip ends, a stop arrives, the node
        stops, or ``duration_ms`` elapses."""
        cap_s = duration_ms / 1000.0 if duration_ms else None
        while True:
            if self._stop_clip.is_set() or self._stop_event.is_set():
                return
            elapsed = time.perf_counter() - self._started_at
            if cap_s is not None and elapsed >= cap_s:
                return
            frame = adapter.next_frame(elapsed)
            if frame is None:
                return
            self._publish_frame(frame)
            wait_s = (frame.duration_ms or _DEFAULT_FRAME_MS) / 1000.0
            if self._stop_clip.wait(timeout=wait_s):
                return
            if frame.is_final:
                return

    def _close_active(self) -> None:
        if self._active is None:
            return
        try:
            self._active.close()
        except Exception as exc:  # noqa: BLE001
            self._log(f"adapter close error: {type(exc).__name__}: {exc}")
        self._active = None
        self._active_asset = ""

    # ── publishing ───────────────────────────────────────────────

    def _publish_frame(self, frame: FrameBuffer) -> None:
        """Publish one rendered frame.

        NOTE: ``MediaFrame`` carries data/width/height only — the
        contract has no field for per-frame duration or end-of-clip, so
        pacing is not expressible on the bus today.  Subscribers that
        need it must currently infer it.  Catalogued in
        ``dev/docs/FRAMEWORK_NEEDS.md`` (FN-2); deliberately not worked
        around here, because a private side-channel would be a second
        copy of a truth the contract should own.
        """
        try:
            self.bus.publish(topics.MediaFrame(
                data=bytes(frame.data),
                width=frame.width,
                height=frame.height,
                node_id=self.name,
            ))
        except Exception:  # noqa: BLE001
            # A publish hiccup must never break the render loop.
            pass

    def _publish_state(self, key: str, asset: str, state: str, *,
                       is_media: bool, reason: str = "") -> None:
        try:
            if is_media:
                self.bus.publish(topics.MediaState(
                    path=asset,
                    kind=key,
                    playing=(state == "playing"),
                    node_id=self.name,
                ))
            else:
                self.bus.publish(topics.AnimationState(
                    adapter=key,
                    asset_path=asset,
                    state=state,
                    progress=1.0 if state == "idle" else 0.0,
                    elapsed_ms=int(
                        (time.perf_counter() - self._started_at) * 1000
                    ) if self._started_at else 0,
                    node_id=self.name,
                ))
        except Exception:  # noqa: BLE001
            pass


def make_animation_node(bus: Any, config: dict | None = None) -> AnimationNode:
    """``module.yaml`` factory: ``(bus, config) -> AnimationNode``.

    Registers the module's own adapters — the framework never needs
    editing to add one.  No decoding or file I/O happens here; that is
    what ``setup()`` and the first ``tick()`` are for.
    """
    config = config or {}
    node = AnimationNode(
        bus=bus,
        width=int(config.get("width", DEFAULT_WIDTH)),
        height=int(config.get("height", DEFAULT_HEIGHT)),
    )
    node.register_default_adapters()
    return node
