"""The `emotes` demo character — the module's shipped face.

A bare install has to be able to show something. These pin the atlas,
its sidecar, and the grid addressing that makes a sprite sheet usable
without pixel arithmetic.
"""

from __future__ import annotations

import pathlib

import pytest
import yaml
from PIL import Image

from jaeger_animation.play import render

CHAR = pathlib.Path(__file__).resolve().parents[1] / \
    "assets/characters/emotes"
SHEET = CHAR / "emotes.png"
PROPS = yaml.safe_load((CHAR / "emotes.props.yaml").read_text())


def test_the_module_ships_a_face():
    """Without this the module renders anything it is handed and has
    nothing of its own to show."""
    assert SHEET.is_file()


def test_sheet_matches_its_sidecar():
    with Image.open(SHEET) as im:
        assert list(im.size) == PROPS["sheet_size"]
    cols, rows = PROPS["grid"]
    cw, ch = PROPS["cell_size"]
    assert PROPS["sheet_size"] == [cols * cw, rows * ch]


def test_eighteen_named_cells():
    cells = PROPS["cells"]
    cols, rows = PROPS["grid"]
    assert len(cells) == cols * rows == 18
    assert sorted(cells.values()) == list(range(18))


def test_every_emotion_has_both_mouth_states():
    """The property that makes this a talking face rather than 18
    unrelated pictures: column = emotion, row = mouth."""
    cols, _ = PROPS["grid"]
    for emotion, col in PROPS["emotions"].items():
        assert PROPS["cells"][f"{emotion}_open"] == col
        assert PROPS["cells"][f"{emotion}_closed"] == col + cols


@pytest.mark.parametrize("name,cell", sorted(PROPS["cells"].items()))
def test_every_named_cell_renders(name, cell):
    frames = render(str(SHEET), adapter="sprite", width=64, height=64,
                    max_frames=1, params={"cell": cell,
                                          "grid": PROPS["grid"]})
    assert len(frames) == 1, name
    assert len(frames[0].data) == 64 * 64 * 4, name


def test_default_face_exists_and_renders():
    default = PROPS["default"]
    assert default in PROPS["cells"]
    frames = render(str(SHEET), adapter="sprite", width=32, height=32,
                    max_frames=1,
                    params={"cell": PROPS["cells"][default],
                            "grid": PROPS["grid"]})
    assert frames


def test_renders_at_led_matrix_and_desktop_sizes():
    """One character, any display — the property the design rests on."""
    for w, h in ((64, 64), (128, 128), (480, 320)):
        frames = render(str(SHEET), adapter="sprite", width=w, height=h,
                        max_frames=1,
                        params={"cell": 0, "grid": PROPS["grid"]})
        assert len(frames[0].data) == w * h * 4


# ── grid addressing (the mechanism, not the character) ───────────

def test_cell_index_is_row_major():
    cols, _ = PROPS["grid"]
    assert PROPS["cells"]["love_open"] == 0
    assert PROPS["cells"]["love_closed"] == cols


def test_out_of_range_cell_raises_rather_than_clamping():
    """Silently showing the wrong face is worse than a clear error."""
    with pytest.raises(ValueError) as exc:
        render(str(SHEET), adapter="sprite", width=32, height=32,
               max_frames=1, params={"cell": 99, "grid": PROPS["grid"]})
    assert "out of range" in str(exc.value)


def test_cell_without_grid_is_an_error():
    with pytest.raises(ValueError):
        render(str(SHEET), adapter="sprite", width=32, height=32,
               max_frames=1, params={"cell": 0})


def test_src_rect_still_works():
    """cell/grid is a convenience; irregular atlases still need src."""
    frames = render(str(SHEET), adapter="sprite", width=32, height=32,
                    max_frames=1, params={"src": (0, 0, 128, 128)})
    assert frames
