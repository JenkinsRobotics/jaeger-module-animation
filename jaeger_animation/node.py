"""AnimationNode — decode/render an asset, publish frames on the bus.

    /act/display/play ─┐                    ┌─▶ /act/display/frame
                       ├─▶  AnimationNode  ─┼─▶ /act/display/state
    /act/display/stop ─┘                    └─▶ /act/display/stats

**The node's job ends at frames on a topic.**  It has no renderer, no
frame callback, no idea whether anything is listening.  A desktop window,
a web canvas, and a driver re-encoding for a 64x64 LED matrix all
subscribe the same way — which is the entire reason one engine can serve
a virtual companion and a physical robot without forking.

One command covers both intents — an avatar expression and an arbitrary
movie.  ``adapter`` names the decoder, or ``"auto"`` picks it from the
file extension.  There used to be two of everything here (an
``/act/animation`` set and an ``/act/media`` set) so that a renderer
showing the face was never handed a movie; the instance segment does
that now, and ``/act/display/face0/`` and ``/act/display/media0/`` are
different prefixes to a subscriber.

**The module declares its whole I/O surface.** The framework provides
pub/sub; deciding what a host can drive and monitor is the module's job.
So alongside pixels and playback state it publishes
``/act/display/stats`` — measured framerate against the clip's target,
frames emitted and dropped, mean decode time, queue depth — on a fixed
low cadence, never per frame. Telemetry rides its own topic because
monitoring a face's health must not require subscribing to its full
pixel stream, which at 4K would be ~1 GB/s.

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
        stats_interval_s: float = 1.0,
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
        # Telemetry. A host monitoring a face needs to know whether it is
        # keeping up; that is a different question from what pixels it is
        # showing, so it rides its own topic on a fixed low cadence.
        self._stats_interval_s = float(stats_interval_s)
        self._frames_emitted = 0
        self._frames_dropped = 0
        self._decode_ms_total = 0.0
        self._decode_samples = 0
        self._window_frames = 0
        self._window_started = time.perf_counter()
        self._fps_actual = 0.0
        self._fps_target = 0.0
        self._last_stats_at = 0.0

    # ── adapter registration ─────────────────────────────────────

    def register_adapter(self, key: str, adapter: AnimationAdapter) -> None:
        """Bind ``key`` (as named in an DisplayCommand) to an adapter."""
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
        self.bus.subscribe(topics.ACT_DISPLAY_PLAY, self._on_play)
        self.bus.subscribe(topics.ACT_DISPLAY_STOP, self._on_stop)
        # Speech amplitude reaches the RUNNING clip. Every adapter has
        # taken `set_runtime_param` since 0.5 and nothing ever called
        # it, so `amplitude_param` was a hook wired at one end only —
        # which is why a procedural face could never react to a voice.
        self.bus.subscribe(topics.ACT_SPEECH_CHUNK, self._on_speech)
        self._log(
            f"subscribed: {topics.ACT_DISPLAY_PLAY}, "
            f"{topics.ACT_DISPLAY_STOP} "
            f"@ {self._width}x{self._height}; "
            f"adapters={list(self.known_adapters())}"
        )

    def tick(self) -> None:
        try:
            key, asset, duration_ms, params = self._pending.get(timeout=0.1)
        except queue.Empty:
            # Idle is still worth reporting — a host must be able to tell
            # "showing nothing" from "node is gone".
            self._maybe_publish_stats()
            return
        self._play(key, asset, duration_ms, params)

    def teardown(self) -> None:
        for topic, handler in (
            (topics.ACT_DISPLAY_PLAY, self._on_play),
            (topics.ACT_DISPLAY_STOP, self._on_stop),
            (topics.ACT_SPEECH_CHUNK, self._on_speech),
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

    def _on_play(self, msg: Any) -> None:
        """One handler for every play request.

        There were two — one for the face, one for arbitrary media —
        back when they were separate topics.  The only thing the media
        path actually did differently was pick its adapter from the
        file extension, which is now what ``adapter="auto"`` means.
        """
        asset = getattr(msg, "asset_path", "") or ""
        if not asset:
            return
        key = getattr(msg, "adapter", "") or "auto"
        if key == "auto":
            key = adapter_for_path(asset)
        self._enqueue(
            key=key,
            asset=asset,
            duration_ms=int(getattr(msg, "duration_ms", 0) or 0),
            params=dict(getattr(msg, "params", None) or {}),
        )

    def _on_speech(self, msg: Any) -> None:
        """Bus thread, and deliberately the ONLY thing that touches the
        adapter from here.

        A parameter push is a float assignment, not a decode, so it does
        not go through the queue: by the time a 30ms audio chunk reached
        the front of a clip queue the sound it describes would be over.
        An adapter that does not take parameters ignores it.
        """
        adapter = self._active
        setter = getattr(adapter, "set_runtime_param", None)
        if setter is None:
            return
        try:
            setter("amplitude", float(getattr(msg, "amplitude", 0.0) or 0.0))
        except Exception:  # noqa: BLE001 — never let a face break the audio
            pass

    def _on_stop(self, msg: Any) -> None:
        self._stop_clip.set()

    def _enqueue(self, *, key: str, asset: str, duration_ms: int,
                 params: dict) -> None:
        """Accept a clip, and PREEMPT whatever is playing.

        The contract has always said so — "a new command preempts
        whatever is playing" — and the implementation only queued. The
        difference shows up the moment anything drives the display
        faster than clips finish: a performance changing expression
        every half second filled the eight-slot queue and then dropped
        the NEWEST request, which is the one that mattered.

        Two changes, and both follow from a display being a STATE rather
        than an event log:

        · a full queue discards the OLDEST. Latest-wins — a superseded
          expression nobody saw is not worth showing late.
        · a new clip ends the current one. Otherwise the newest command
          waits out however long the previous clip runs, which for a
          held image is forever.

        Something that genuinely wants a sequence should send an
        mscript or a timeline, both of which sequence internally and
        arrive here as ONE clip.
        """
        if not asset:
            return
        while True:
            try:
                self._pending.put_nowait((key, asset, duration_ms, params))
                break
            except queue.Full:
                try:
                    stale_key, stale_asset, _d, _p = self._pending.get_nowait()
                    self._frames_dropped += 1
                    self._log(f"superseded {stale_key!r} clip {stale_asset!r}")
                except queue.Empty:      # drained under us; try again
                    continue
        self._stop_clip.set()

    # ── playback ─────────────────────────────────────────────────

    def _play(self, key: str, asset: str, duration_ms: int,
              params: dict) -> None:
        adapter = self._adapters.get(key)
        if adapter is None:
            self._log(f"unknown adapter {key!r}; skipping {asset!r}")
            self._publish_state(key, asset, "idle",
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
            self._publish_state(key, asset, "idle",
                                reason=f"{type(exc).__name__}: {exc}")
            return

        self._active = adapter
        self._active_key = key
        self._active_asset = asset
        self._started_at = time.perf_counter()
        self._stop_clip.clear()
        self._publish_state(key, asset, "playing")

        try:
            self._stream(adapter, duration_ms)
        except Exception as exc:  # noqa: BLE001
            self._log(f"stream error on {asset!r}: "
                      f"{type(exc).__name__}: {exc}")

        self._close_active()
        self._publish_state(key, asset, "idle")

    def _stream(self, adapter: AnimationAdapter, duration_ms: int) -> None:
        """Emit frames until the clip ends, a stop arrives, the node
        stops, or ``duration_ms`` elapses."""
        cap_s = duration_ms / 1000.0 if duration_ms else None
        while True:
            if self._stop_clip.is_set() or self._stop_event.is_set():
                return
            elapsed = time.perf_counter() - self._started_at
            if cap_s is not None and elapsed >= cap_s:
                return
            t0 = time.perf_counter()
            frame = adapter.next_frame(elapsed)
            self._decode_ms_total += (time.perf_counter() - t0) * 1000.0
            self._decode_samples += 1
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

        Carries the pacing the decoder genuinely knows —
        ``duration_ms`` and ``is_final`` — so a subscriber never has to
        guess a frame rate or infer the end of a clip from a separate
        topic with no ordering guarantee.

        ``frame.data`` is handed over WITHOUT copying.  FrameBuffer is
        immutable by convention and every adapter builds a fresh buffer
        per frame, so a defensive ``bytes(...)`` here would duplicate
        the largest object in the system on the hottest path.
        """
        self._frames_emitted += 1
        self._window_frames += 1
        self._fps_target = (
            1000.0 / frame.duration_ms if frame.duration_ms else 0.0
        )
        try:
            self.bus.publish(topics.DisplayFrame(
                data=frame.data,
                width=frame.width,
                height=frame.height,
                duration_ms=frame.duration_ms,
                is_final=frame.is_final,
                seq=self._frames_emitted,
                node_id=self.name,
            ))
        except Exception:  # noqa: BLE001
            # A publish hiccup must never break the render loop.
            pass
        self._maybe_publish_stats()

    def _maybe_publish_stats(self) -> None:
        """Emit telemetry on a fixed cadence, never per frame.

        Per-frame stats would double the message rate of the thing they
        are meant to measure."""
        now = time.perf_counter()
        if now - self._last_stats_at < self._stats_interval_s:
            return
        self._last_stats_at = now
        window = now - self._window_started
        if window > 0:
            self._fps_actual = self._window_frames / window
        self._window_frames = 0
        self._window_started = now
        mean_decode = (
            self._decode_ms_total / self._decode_samples
            if self._decode_samples else 0.0
        )
        try:
            self.bus.publish(topics.DisplayStats(
                adapter=self._active_key,
                asset_path=self._active_asset,
                width=self._width,
                height=self._height,
                fps_actual=round(self._fps_actual, 2),
                fps_target=round(self._fps_target, 2),
                frames_emitted=self._frames_emitted,
                frames_dropped=self._frames_dropped,
                decode_ms=round(mean_decode, 3),
                queue_depth=self._pending.qsize(),
                node_id=self.name,
            ))
        except Exception:  # noqa: BLE001
            pass

    def _publish_state(self, key: str, asset: str, state: str,
                       reason: str = "") -> None:
        try:
            self.bus.publish(topics.DisplayState(
                adapter=key,
                asset_path=asset,
                state=state,
                progress=1.0 if state == "idle" else 0.0,
                elapsed_ms=int(
                    (time.perf_counter() - self._started_at) * 1000
                ) if self._started_at else 0,
                reason=reason,
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
    from .config import AnimationConfig

    # Validate through the module's own settings model, so a bad value
    # fails here with a field name rather than deep in a render loop.
    cfg = AnimationConfig(**(config or {}))
    node = AnimationNode(
        bus=bus,
        width=cfg.width,
        height=cfg.height,
        queue_maxsize=cfg.queue_maxsize,
        stats_interval_s=cfg.stats_interval_s,
    )
    node.register_default_adapters()
    return node
