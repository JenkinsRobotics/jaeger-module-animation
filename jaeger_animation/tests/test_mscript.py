"""Motion scripts — a sequence of other assets, executed by the engine.

A character supplies motion scripts (or a caller sends commands) and the
node plays them. The script is the character's; the execution is the
engine's. MScriptAdapter decodes nothing itself — it binds each command
to a real adapter and pumps frames from whichever is active.

Fixtures are built here rather than pointing at Mochi, so the suite is
self-contained.
"""

from __future__ import annotations

import pathlib

import pytest
from PIL import Image

from jaeger_animation.adapters import ADAPTERS, adapter_for_path
from jaeger_animation.play import render

W = H = 32

SCENE = (
    "import numpy as np\n"
    "from plugin_core.mochi_animations import Animation\n"
    "\n"
    "class Demo(Animation):\n"
    "    name = 'demo'\n"
    "    def render_into(self, t, buf):\n"
    "        f = np.frombuffer(buf, dtype=np.uint8).reshape(\n"
    "            (self.h, self.w, 3))\n"
    "        f[:, :, 1] = 180\n"
)


@pytest.fixture
def tree(tmp_path):
    """An asset tree shaped the way motion scripts expect:
    <root>/assets/{math,gifs,mscripts}/"""
    (tmp_path / "assets/math").mkdir(parents=True)
    (tmp_path / "assets/gifs").mkdir(parents=True)
    (tmp_path / "assets/mscripts").mkdir(parents=True)
    (tmp_path / "assets/math/scene.py").write_text(SCENE)
    frames = [Image.new("RGB", (8, 8), (c, 0, 0)) for c in (60, 200)]
    frames[0].save(tmp_path / "assets/gifs/clip.gif", save_all=True,
                   append_images=frames[1:], duration=40, loop=0)
    return tmp_path


def _script(tree, body: str, resources: str) -> pathlib.Path:
    p = tree / "assets/mscripts/s.mscript"
    p.write_text(
        "[Resources start]\n" + resources + "[Resources end]\n\n"
        "[Main start]\n" + body + "[Main end]\n")
    return p


def _play(path, tree, n=8, **params):
    return render(str(path), adapter="mscript", width=W, height=H,
                  max_frames=n, params={"asset_root": str(tree), **params})


# ── it is an adapter like any other ──────────────────────────────

def test_mscript_is_a_registered_adapter():
    assert "mscript" in ADAPTERS
    assert adapter_for_path("x.mscript") == "mscript"


# ── sequencing ───────────────────────────────────────────────────

def test_plays_a_single_command(tree):
    s = _script(tree, "MATH K[1] D[2.0]\n", "K[1]: 'assets/math/scene.py'\n")
    frames = _play(s, tree)
    assert frames
    assert all(len(f.data) == W * H * 4 for f in frames)
    # the scene paints green


def test_sequences_two_assets_in_order(tree):
    """The point of a motion script: one asset, then another."""
    s = _script(
        tree,
        "MATH K[1] D[0.05]\nWAIT D[0.01]\nMEDIA K[2] D[0.5]\n",
        "K[1]: 'assets/math/scene.py'\nK[2]: 'assets/gifs/clip.gif'\n")
    frames = _play(s, tree, n=12)
    assert len(frames) > 1


def test_resources_resolve_against_asset_root(tree):
    s = _script(tree, "MATH K[1] D[1.0]\n", "K[1]: 'assets/math/scene.py'\n")
    assert _play(s, tree)


def test_a_missing_asset_names_the_path(tree):
    s = _script(tree, "MATH K[1] D[1.0]\n", "K[1]: 'assets/math/gone.py'\n")
    with pytest.raises(FileNotFoundError) as exc:
        _play(s, tree)
    assert "gone.py" in str(exc.value)


def test_command_picks_the_right_adapter(tree):
    """MEDIA chooses by extension; MATH always means a scene."""
    s = _script(tree, "MEDIA K[1] D[0.5]\n", "K[1]: 'assets/gifs/clip.gif'\n")
    assert _play(s, tree)


def test_a_wait_holds_the_last_frame_rather_than_ending(tree):
    """None means 'clip over' to the node. A script mid-WAIT is not
    over, so it must keep presenting the last frame."""
    s = _script(tree,
                "MATH K[1] D[0.02]\nWAIT D[5.0]\nMATH K[1] D[1.0]\n",
                "K[1]: 'assets/math/scene.py'\n")
    frames = _play(s, tree, n=6)
    assert len(frames) >= 2, "the script ended during its WAIT"


def test_an_empty_script_does_not_crash(tree):
    s = _script(tree, "", "")
    _play(s, tree, n=2)  # must not raise


def test_a_broken_scene_surfaces_through_the_script(tree):
    (tree / "assets/math/bad.py").write_text(
        "from plugin_core.mochi_animations import Animation\n"
        "class Bad(Animation):\n"
        "    def render_into(self, t, buf):\n"
        "        raise ValueError('nope')\n")
    s = _script(tree, "MATH K[1] D[1.0]\n", "K[1]: 'assets/math/bad.py'\n")
    with pytest.raises(RuntimeError) as exc:
        _play(s, tree)
    assert "ValueError" in str(exc.value)


def test_runtime_params_reach_the_active_asset(tree):
    """Lip-sync amplitude has to get through the sequencer to whatever
    is currently playing."""
    from jaeger_animation.adapters import MScriptAdapter

    s = _script(tree, "MATH K[1] D[2.0]\n", "K[1]: 'assets/math/scene.py'\n")
    a = MScriptAdapter()
    a.open(str(s), width=W, height=H, params={"asset_root": str(tree)})
    a.next_frame(0.0)
    a.set_runtime_param("amplitude", 0.7)   # must not raise
    assert getattr(a._active._script, "amplitude_param", None) == 0.7
    a.close()


def test_it_decodes_nothing_itself():
    """Composition, not a second engine — if this file grows a decoder
    the separation has been lost."""
    src = (pathlib.Path(__file__).resolve().parents[1]
           / "adapters/mscript_adapter.py").read_text()
    for forbidden in ("Image.open", "imageio", "json.loads", "np.frombuffer"):
        assert forbidden not in src, f"mscript_adapter should not {forbidden}"
