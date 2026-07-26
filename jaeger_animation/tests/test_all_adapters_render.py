"""EVERY adapter renders — not just constructs.

The gap this closes: the suite used to assert adapters could be
instantiated and only ever RENDERED image and gif. Three of six were
broken for different reasons and all three looked fine:

  bitmap  routed .bmp to it, but it reads 1-bit JSON — UnicodeDecodeError
  math    every real scene subclasses Animation, the adapter looked for
          MathScript, and scenes imported a package name we do not have
  video   imageio missing raised a bare ModuleNotFoundError

Constructing an adapter proves nothing. These render one real asset
through each.
"""

from __future__ import annotations

import json
import os
import pathlib

import numpy as np
import pytest
from PIL import Image

from jaeger_animation.adapters import ADAPTERS, adapter_for_path
from jaeger_animation.play import render

SHEET = pathlib.Path(__file__).resolve().parents[1] / \
    "assets/characters/emotes/emotes.png"
W = H = 32


@pytest.fixture(scope="module")
def assets(tmp_path_factory):
    """One real asset per adapter."""
    d = tmp_path_factory.mktemp("assets")
    Image.new("RGBA", (8, 8), (200, 60, 40, 255)).save(d / "a.png")
    Image.new("RGB", (8, 8), (10, 120, 30)).save(d / "a.bmp")
    frames = [Image.new("RGB", (8, 8), (c, 0, 0)) for c in (50, 150, 250)]
    frames[0].save(d / "a.gif", save_all=True, append_images=frames[1:],
                   duration=40, loop=0)
    # 1-bit packed monochrome, Adafruit-GFX style — what `bitmap` means.
    (d / "a.json").write_text(json.dumps(
        {"width": 8, "height": 8, "data": [0xFF, 0x81, 0x81, 0xFF] * 2}))
    d.joinpath("scene.py").write_text(
        "import numpy as np\n"
        "from plugin_core.mochi_animations import Animation\n"
        "\n"
        "class Demo(Animation):\n"
        "    name = 'demo'\n"
        "    def render_into(self, t, buf):\n"
        "        f = np.frombuffer(buf, dtype=np.uint8).reshape(\n"
        "            (self.h, self.w, 3))\n"
        "        f[:, :, 0] = 200\n"
    )
    return d


def _render(asset, adapter, params=None, n=3):
    return render(str(asset), adapter=adapter, width=W, height=H,
                  max_frames=n, params=params or {})


# ── one test per adapter ─────────────────────────────────────────

def test_image_renders(assets):
    frames = _render(assets / "a.png", "image")
    assert frames and len(frames[0].data) == W * H * 4


def test_bmp_is_an_image_not_a_bitmap(assets):
    """`bitmap` means 1-bit JSON. A .bmp is a full-colour raster."""
    assert adapter_for_path("x.bmp") == "image"
    frames = _render(assets / "a.bmp", "image")
    assert frames and len(frames[0].data) == W * H * 4


def test_gif_renders_multiple_frames(assets):
    frames = _render(assets / "a.gif", "gif")
    assert len(frames) > 1


def test_bitmap_renders_packed_monochrome(assets):
    assert adapter_for_path("x.json") == "bitmap"
    frames = _render(assets / "a.json", "bitmap")
    assert frames and len(frames[0].data) == W * H * 4


def test_sprite_renders_a_sheet_cell():
    frames = _render(SHEET, "sprite", {"cell": 0, "grid": (9, 2)})
    assert frames and len(frames[0].data) == W * H * 4


def test_math_renders_a_procedural_scene(assets):
    """The scene subclasses Animation and imports plugin_core.* — the
    shape every real scene in Mochi and JaegerAI has."""
    frames = _render(assets / "scene.py", "math")
    assert len(frames) == 3
    assert any(b for b in frames[0].data), "scene drew nothing"


def test_video_renders(assets, tmp_path):
    imageio = pytest.importorskip(
        "imageio", reason="video needs the [video] extra")
    import imageio.v3 as iio
    path = tmp_path / "a.mp4"
    iio.imwrite(path, np.random.randint(0, 255, (6, 16, 16, 3),
                                        dtype=np.uint8), fps=10)
    frames = _render(path, "video")
    assert frames and len(frames[0].data) == W * H * 4


# ── the guard that stops this recurring ──────────────────────────

def test_every_declared_adapter_has_a_render_test():
    """A new adapter must arrive with proof it renders, not just that it
    constructs. Constructing is what let three broken ones ship."""
    tested = {"image", "bitmap", "gif", "sprite", "math", "video"}
    assert set(ADAPTERS) == tested, (
        f"adapters without a render test: {set(ADAPTERS) - tested}")


def test_extension_routing_matches_what_each_adapter_consumes():
    for ext, key in ((".png", "image"), (".bmp", "image"), (".gif", "gif"),
                     (".json", "bitmap"), (".mp4", "video"), (".py", "math")):
        assert adapter_for_path(f"x{ext}") == key, ext


def test_a_broken_scene_raises_rather_than_rendering_nothing(assets):
    """Returning None on error was indistinguishable from 'clip ended',
    which is how a scene that never rendered looked like one that
    finished."""
    bad = assets / "bad_scene.py"
    bad.write_text(
        "from plugin_core.mochi_animations import Animation\n"
        "class Bad(Animation):\n"
        "    def render_into(self, t, buf):\n"
        "        raise ZeroDivisionError('boom')\n"
    )
    with pytest.raises(RuntimeError) as exc:
        _render(bad, "math")
    assert "ZeroDivisionError" in str(exc.value)


def test_scene_import_aliases_do_not_leak(assets):
    """The loader exposes plugin_core/mscript only while importing a
    scene — leaving them in sys.modules would be this package quietly
    claiming generic top-level names."""
    import sys
    _render(assets / "scene.py", "math", n=1)
    assert "plugin_core" not in sys.modules
    assert "mscript" not in sys.modules


def test_video_without_the_extra_names_the_extra():
    """A missing optional codec must degrade with instructions, not a
    bare ModuleNotFoundError naming a package nobody asked for."""
    import builtins
    import importlib

    from jaeger_animation.adapters.video_adapter import VideoAdapter

    real = builtins.__import__

    def _no_imageio(name, *a, **k):
        if name == "imageio" or name.startswith("imageio."):
            raise ImportError("No module named 'imageio'")
        return real(name, *a, **k)

    builtins.__import__ = _no_imageio
    try:
        with pytest.raises(RuntimeError) as exc:
            VideoAdapter().open("x.mp4", width=8, height=8, params={})
    finally:
        builtins.__import__ = real
    assert "jaeger-animation[video]" in str(exc.value)
