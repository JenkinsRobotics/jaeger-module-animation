"""The engine: adapters render, and the node puts frames on the bus."""

from __future__ import annotations

import threading
import time

import pytest
from PIL import Image

from jaeger_os.transport import InProcBus, topics

from jaeger_animation import make_animation_node
from jaeger_animation.adapters import ADAPTERS, adapter_for_path
from jaeger_animation.play import render


# ── fixtures ─────────────────────────────────────────────────────

@pytest.fixture
def png(tmp_path):
    p = tmp_path / "solid.png"
    Image.new("RGBA", (8, 8), (200, 60, 40, 255)).save(p)
    return str(p)


@pytest.fixture
def gif(tmp_path):
    p = tmp_path / "clip.gif"
    frames = [Image.new("RGBA", (8, 8), (c, 0, 0, 255)) for c in (50, 150, 250)]
    frames[0].save(p, save_all=True, append_images=frames[1:],
                   duration=40, loop=0)
    return str(p)


@pytest.fixture
def bus():
    b = InProcBus()
    yield b
    b.close()


def _wait_for(predicate, timeout=3.0) -> bool:
    """InProcBus delivers on a worker thread, so publish() is async.
    Asserting without waiting would pass even if delivery were broken."""
    deadline = time.perf_counter() + timeout
    while time.perf_counter() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


# ── adapters ─────────────────────────────────────────────────────

def test_image_renders_one_frame_at_requested_size(png):
    frames = render(png, width=32, height=32, max_frames=5)
    assert len(frames) == 1
    f = frames[0]
    assert (f.width, f.height) == (32, 32)
    assert len(f.data) == 32 * 32 * 4


def test_gif_renders_multiple_frames(gif):
    frames = render(gif, width=16, height=16, max_frames=6)
    assert len(frames) > 1
    assert all(len(f.data) == 16 * 16 * 4 for f in frames)


@pytest.mark.parametrize("size", [(8, 8), (64, 64), (24, 1)])
def test_renders_at_any_geometry(gif, size):
    """The property the whole design rests on: one asset, any display —
    a desktop window, a 64x64 LED matrix, a 24-pixel strip."""
    w, h = size
    frames = render(gif, width=w, height=h, max_frames=2)
    assert frames
    assert all(len(f.data) == w * h * 4 for f in frames)


def test_extension_routing():
    assert adapter_for_path("a.gif") == "gif"
    assert adapter_for_path("a.png") == "image"
    assert adapter_for_path("a.mp4") == "video"
    assert adapter_for_path("scene.py") == "math"
    # Unknown extensions fall back rather than raising — a bad guess
    # surfaces as a decode error, not an import-time crash.
    assert adapter_for_path("a.unknown") == "image"


def test_every_declared_adapter_constructs():
    for key, cls in ADAPTERS.items():
        assert cls() is not None, key


# ── the node ─────────────────────────────────────────────────────

def _run(node):
    t = threading.Thread(target=node.run, daemon=True)
    t.start()
    time.sleep(0.2)
    return t


def test_node_publishes_frames_on_the_bus(bus, png):
    """Frames reach ANY subscriber. This is what lets a window and an
    LED matrix render from one engine."""
    frames = []
    bus.subscribe(topics.SENSE_MEDIA_FRAME, frames.append)

    node = make_animation_node(bus, {"width": 16, "height": 16})
    t = _run(node)
    try:
        bus.publish(topics.AnimationCommand(
            adapter="image", asset_path=png, duration_ms=100))
        assert _wait_for(lambda: frames), "no frame published"
        f = frames[0]
        assert (f.width, f.height) == (16, 16)
        assert len(f.data) == 16 * 16 * 4
    finally:
        node.stop()
        t.join(timeout=2)


def test_node_reports_playing_then_idle(bus, png):
    states = []
    bus.subscribe(topics.SENSE_ANIMATION_STATE, states.append)

    node = make_animation_node(bus, {"width": 8, "height": 8})
    t = _run(node)
    try:
        bus.publish(topics.AnimationCommand(
            adapter="image", asset_path=png, duration_ms=50))
        assert _wait_for(lambda: any(s.state == "idle" for s in states))
        assert [s.state for s in states][:2] == ["playing", "idle"]
        assert states[0].asset_path == png
    finally:
        node.stop()
        t.join(timeout=2)


def test_media_intent_publishes_media_state(bus, gif):
    """/act/media and /act/animation share the engine but stay distinct
    intents: 'play this movie' vs 'make the face do this'."""
    media_states = []
    frames = []
    bus.subscribe(topics.SENSE_MEDIA_STATE, media_states.append)
    bus.subscribe(topics.SENSE_MEDIA_FRAME, frames.append)

    node = make_animation_node(bus, {"width": 8, "height": 8})
    t = _run(node)
    try:
        bus.publish(topics.MediaCommand(path=gif, loop=False))
        assert _wait_for(lambda: frames), "no frames from /act/media"
        assert _wait_for(lambda: any(s.playing for s in media_states))
    finally:
        node.stop()
        t.join(timeout=2)


def test_unknown_adapter_does_not_kill_the_node(bus, png):
    node = make_animation_node(bus, {})
    t = _run(node)
    try:
        bus.publish(topics.AnimationCommand(
            adapter="nonexistent", asset_path=png))
        time.sleep(0.3)
        assert node.state.name == "RUNNING"
    finally:
        node.stop()
        t.join(timeout=2)


def test_missing_asset_does_not_kill_the_node(bus):
    """A bad file leaves the face as it was; it never takes the node
    down."""
    node = make_animation_node(bus, {})
    t = _run(node)
    try:
        bus.publish(topics.AnimationCommand(
            adapter="image", asset_path="/nonexistent/nope.png"))
        time.sleep(0.3)
        assert node.state.name == "RUNNING"
    finally:
        node.stop()
        t.join(timeout=2)


def test_stop_interrupts_a_running_clip(bus, gif):
    frames = []
    bus.subscribe(topics.SENSE_MEDIA_FRAME, frames.append)

    node = make_animation_node(bus, {"width": 8, "height": 8})
    t = _run(node)
    try:
        bus.publish(topics.AnimationCommand(
            adapter="gif", asset_path=gif, params={"loop": True}))
        assert _wait_for(lambda: frames)
        bus.publish(topics.AnimationStop())
        time.sleep(0.3)
        settled = len(frames)
        time.sleep(0.3)
        assert len(frames) == settled, "frames still flowing after stop"
    finally:
        node.stop()
        t.join(timeout=2)


def test_factory_registers_every_adapter(bus):
    """The module owns its adapter list — adding one must never require
    editing JaegerOS."""
    node = make_animation_node(bus, {})
    assert set(node.known_adapters()) == set(ADAPTERS)


def test_health_reports_geometry_and_adapters(bus):
    node = make_animation_node(bus, {"width": 64, "height": 64})
    h = node.health()
    assert h["geometry"] == "64x64"
    assert "gif" in h["adapters"]
