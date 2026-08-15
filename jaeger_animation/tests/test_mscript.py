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

EVENT_SCENE = (
    "import numpy as np\n"
    "from plugin_core.mochi_animations import Animation\n"
    "class EventDemo(Animation):\n"
    "    def __init__(self, w, h):\n"
    "        super().__init__(w, h)\n"
    "        self.value = 10\n"
    "    def on_event(self, event, **kwargs):\n"
    "        if event == 'go': self.value = int(kwargs['VALUE'])\n"
    "    def render_into(self, t, buf):\n"
    "        f = np.frombuffer(buf, dtype=np.uint8).reshape((self.h, self.w, 3))\n"
    "        f[:, :, 1] = self.value\n"
)


@pytest.fixture
def tree(tmp_path):
    """An asset tree shaped the way motion scripts expect:
    <root>/assets/{math,gifs,mscripts}/"""
    (tmp_path / "assets/math").mkdir(parents=True)
    (tmp_path / "assets/gifs").mkdir(parents=True)
    (tmp_path / "assets/sprites").mkdir(parents=True)
    (tmp_path / "assets/mscripts").mkdir(parents=True)
    (tmp_path / "assets/math/scene.py").write_text(SCENE)
    (tmp_path / "assets/math/event.py").write_text(EVENT_SCENE)
    frames = [Image.new("RGB", (8, 8), (c, 0, 0)) for c in (60, 200)]
    frames[0].save(tmp_path / "assets/gifs/clip.gif", save_all=True,
                   append_images=frames[1:], duration=40, loop=0)
    sheet = Image.new("RGB", (16, 8), (255, 0, 0))
    sheet.paste(Image.new("RGB", (8, 8), (0, 200, 0)), (8, 0))
    sheet.save(tmp_path / "assets/sprites/sheet.png")
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


def test_legacy_sprite_tokens_reach_the_modern_adapter(tree):
    s = _script(
        tree,
        "SPRITE K[1] D[0.5] SRC[8,0,8,8]\n",
        "K[1]: 'assets/sprites/sheet.png'\n",
    )
    frames = _play(s, tree)
    assert frames
    # The requested right-hand crop is green, proving SRC was translated.
    center = ((H // 2) * W + (W // 2)) * 4
    assert frames[0].data[center:center + 3] == bytes((0, 200, 0))


def test_legacy_media_tokens_translate_to_adapter_params():
    from jaeger_animation.adapters.mscript_adapter import _clean

    assert _clean("VIDEO", {
        "K": 1, "D": 2.0, "BG": [1, 2, 3], "SPD": 1.5,
        "FIT": "fit", "LOOP": "NO",
    }) == {
        "letterbox_rgb": [1, 2, 3], "speed": 1.5,
        "fit": "contain", "loop": False,
    }


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


def test_legacy_event_mutates_the_existing_keyed_scene(tree):
    from jaeger_animation.adapters import MScriptAdapter

    s = _script(
        tree,
        "MATH K[1] D[0.1]\nMATH K[1] EVENT[go] VALUE[211]\n",
        "K[1]: 'assets/math/event.py'\n",
    )
    a = MScriptAdapter()
    a.open(str(s), width=W, height=H, params={"asset_root": str(tree)})
    before = a.next_frame(0.0)
    original = a._active
    after = a.next_frame(0.1)
    assert a._active is original
    assert before.data[1] == 10
    assert after.data[1] == 211
    a.close()


# ── control flow: LBL / JMP ──────────────────────────────────────
#
# The language spec has carried `LBL[id]` and `JMP LBL[id]` since v2.0
# and no engine ever implemented them, so every motion script written
# until now runs top to bottom exactly once. These are the tests for
# the loop that was always documented.

def _program(tree, body: str, resources: str = "K[1]: 'assets/math/scene.py'\n"):
    """The sequencer alone — control flow is decided here, before any
    adapter is asked for a pixel, so this reads it without rendering."""
    from jaeger_animation.procedural.mscript_engine import MscriptScript

    return MscriptScript(str(_script(tree, body, resources)))


def _run(program, ticks=(0.0, 1.0, 2.0, 3.0, 4.0)) -> list[str]:
    return [c.name for t in ticks for c in program.update(t)]


def test_a_jump_loops_back_to_its_label(tree):
    """The whole point: a script that repeats until something stops it.
    Without JMP the MATH below can only ever be issued once."""
    program = _program(
        tree, "LBL[1]\nMATH K[1] D[0.1]\nWAIT D[0.1]\nJMP LBL[1]\n")
    assert _run(program).count("MATH") >= 2, \
        "the script ran once and stopped — JMP did not go back to LBL[1]"


def test_a_label_never_reaches_an_adapter(tree):
    """LBL marks a position; it is not something to render. Emitting it
    would send an unknown command to the adapter every loop."""
    program = _program(tree, "LBL[1]\nMATH K[1] D[0.1]\n")
    # Not `"LBL" not in names` — before this was implemented the command
    # came through spelled `LBL[1]`, bracket and all, and that spelling
    # would have satisfied the looser check while still reaching an
    # adapter that has no idea what it is.
    assert not [n for n in _run(program) if n.startswith("LBL")]


def test_a_label_name_is_a_comment(tree):
    """`LBL[1:top]` — the spec says the name is for the reader. If the
    engine took `1:top` as the id, the jump below would not resolve."""
    program = _program(
        tree, "LBL[1:top]\nMATH K[1] D[0.1]\nWAIT D[0.1]\nJMP LBL[1]\n")
    assert _run(program).count("MATH") >= 2


def test_a_jump_to_a_missing_label_carries_on(tree):
    """A typo must not take the performance down. The jump is skipped
    and the rest of the script still plays."""
    program = _program(
        tree, "MATH K[1] D[0.1]\nJMP LBL[9]\nWAIT D[0.1]\nMATH K[1] D[0.1]\n")
    assert _run(program).count("MATH") == 2


def test_a_key_name_is_a_comment_too(tree):
    """`K[1:eye]` — the spec allows a name on ANY keyframe reference, not
    just labels. Taking `1:eye` as the id resolved no resource, so the
    command was silently skipped and nothing was drawn."""
    program = _program(tree, "MATH K[1:scene] D[0.1]\n")
    issued = program.update(0.0)
    assert [c.name for c in issued] == ["MATH"]
    assert issued[0].args["asset_path"] == "assets/math/scene.py"


def test_a_loop_with_no_wait_stops_instead_of_hanging(tree):
    """`LBL[1] … JMP LBL[1]` with nothing to wait on would spin inside
    one update() forever, and a hung update() is a frozen window — the
    engine runs on the render thread. It must return."""
    program = _program(tree, "LBL[1]\nMATH K[1]\nJMP LBL[1]\n")
    issued = program.update(0.0)          # must not hang
    assert len(issued) < 10_000
    assert program.update(1.0) == [], "the runaway script never stopped"


def test_it_decodes_nothing_itself():
    """Composition, not a second engine — if this file grows a decoder
    the separation has been lost."""
    src = (pathlib.Path(__file__).resolve().parents[1]
           / "adapters/mscript_adapter.py").read_text()
    for forbidden in ("Image.open", "imageio", "json.loads", "np.frombuffer"):
        assert forbidden not in src, f"mscript_adapter should not {forbidden}"


# ── a display is a state, not an event log ───────────────────────

def test_a_new_clip_preempts_and_the_newest_always_wins(tree):
    """The contract says "a new command preempts whatever is playing",
    and the node only queued. Anything driving the display faster than
    clips finish — a performance changing expression twice a second —
    filled the eight-slot queue and dropped the NEWEST request, which is
    the only one that mattered."""
    import queue as _queue

    from jaeger_animation.node import AnimationNode

    class _Bus:
        def publish(self, *a, **k):
            pass

        def subscribe(self, *a, **k):
            pass

        def unsubscribe(self, *a, **k):
            pass

    node = AnimationNode(bus=_Bus(), width=W, height=H, queue_maxsize=2)
    for n in range(6):
        node._enqueue(key="bitmap", asset=f"face_{n}.json",
                      duration_ms=0, params={})

    queued = []
    while True:
        try:
            queued.append(node._pending.get_nowait()[1])
        except _queue.Empty:
            break
    # oldest discarded, newest kept — a superseded expression nobody saw
    # is not worth showing late
    assert queued == ["face_4.json", "face_5.json"]
    # and the clip on screen was told to end
    assert node._stop_clip.is_set()


def test_an_mscript_still_sequences_internally(tree):
    """Preempting must not break a script: a whole mscript arrives as
    ONE clip and does its own sequencing, so nothing preempts anything."""
    s = _script(
        tree,
        "MATH K[1] D[0.05]\nWAIT D[0.01]\nMEDIA K[2] D[0.5]\n",
        "K[1]: 'assets/math/scene.py'\nK[2]: 'assets/gifs/clip.gif'\n")
    assert len(_play(s, tree, n=12)) > 1
