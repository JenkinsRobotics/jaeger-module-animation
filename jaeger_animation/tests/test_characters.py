"""Character packs — the format, the loader, and the shipped pack.

This is the contract with Anima Studio (it exports packs, this engine
consumes them), so the loader is strict and every failure names the file.
"""

from __future__ import annotations

import pathlib

import pytest

from jaeger_animation.characters import (
    KINDS, BUILTIN_DIR, CharacterError, discover_characters, load_character,
)
from jaeger_animation.play import render

VALID = """\
schema: character/v1
character: test
kind: sprite_sheet
render: {adapter: sprite, asset: sheet.png, grid: [2, 2]}
expressions: {a: {column: 0}, b: {column: 1}}
mouth_states: {open: 0, closed: 1}
default_expression: a
default_mouth: closed
"""


@pytest.fixture
def pack(tmp_path):
    """A minimal valid pack, so malformed cases differ by one line."""
    from PIL import Image
    Image.new("RGBA", (64, 64)).save(tmp_path / "sheet.png")
    (tmp_path / "character.yaml").write_text(VALID)
    return tmp_path


# ── the shipped pack ─────────────────────────────────────────────

def test_the_module_ships_a_discoverable_character():
    chars = discover_characters()
    assert "emotes" in chars


def test_shipped_character_plays_every_expression_in_both_mouths():
    c = discover_characters()["emotes"]
    seen = set()
    for expr in c.expressions:
        for mouth in c.mouth_states:
            params = c.play_params(expr, mouth)
            seen.add(params["cell"])
            frames = render(str(c.asset_path), adapter=c.adapter,
                            width=64, height=64, max_frames=1, params=params)
            assert len(frames) == 1, f"{expr}/{mouth}"
    # 9 expressions x 2 mouths must address 18 DISTINCT cells — an
    # off-by-one in the row maths would collide instead of failing.
    assert len(seen) == 18


def test_defaults_let_a_caller_show_a_face_knowing_nothing():
    c = discover_characters()["emotes"]
    params = c.play_params()
    assert render(str(c.asset_path), adapter=c.adapter, width=32,
                  height=32, max_frames=1, params=params)


def test_asset_path_resolves_inside_the_pack():
    c = discover_characters()["emotes"]
    assert c.asset_path.is_file()
    assert c.asset_path.parent == c.root


# ── the format is enforced ───────────────────────────────────────

def test_a_valid_pack_loads(pack):
    c = load_character(pack)
    assert c.name == "test" and c.kind == "sprite_sheet"
    assert c.play_params("b", "open") == {"cell": 1, "grid": (2, 2)}
    assert c.play_params() == {"cell": 2, "grid": (2, 2)}  # a/closed


@pytest.mark.parametrize("bad,expect", [
    ("schema: nope\n", "schema"),
    ("kind: banana\n", "kind"),
    ("expressions: {}\n", "expression"),
    ("default_expression: ghost\n", "default_expression"),
    ("default_mouth: ghost\n", "default_mouth"),
])
def test_malformed_packs_are_rejected_by_file_name(pack, bad, expect):
    """A broken pack must fail loudly, not render the wrong face."""
    key = bad.split(":")[0]
    lines = [ln for ln in VALID.splitlines()
             if not ln.startswith(f"{key}:")]
    (pack / "character.yaml").write_text("\n".join(lines) + "\n" + bad)
    with pytest.raises(CharacterError) as exc:
        load_character(pack)
    assert "character.yaml" in str(exc.value)
    assert expect in str(exc.value)


def test_a_missing_asset_is_caught_at_load(pack):
    (pack / "sheet.png").unlink()
    with pytest.raises(CharacterError) as exc:
        load_character(pack)
    assert "does not exist" in str(exc.value)


def test_a_column_outside_the_grid_is_caught_at_load(pack):
    (pack / "character.yaml").write_text(
        VALID.replace("b: {column: 1}", "b: {column: 9}"))
    with pytest.raises(CharacterError) as exc:
        load_character(pack)
    assert "outside" in str(exc.value)


def test_unknown_expression_names_what_is_available(pack):
    with pytest.raises(CharacterError) as exc:
        load_character(pack).play_params("ghost")
    assert "'a'" in str(exc.value)


def test_an_unimplemented_kind_says_so_rather_than_rendering_nothing(pack):
    (pack / "character.yaml").write_text(
        VALID.replace("kind: sprite_sheet", "kind: procedural"))
    with pytest.raises(CharacterError) as exc:
        load_character(pack).play_params("a")
    assert "sprite_sheet" in str(exc.value)


def test_declared_kinds_are_the_documented_set():
    assert KINDS == {"sprite_sheet", "clip_set", "procedural", "rig"}


# ── discovery ────────────────────────────────────────────────────

def test_folders_without_a_manifest_are_skipped(tmp_path):
    (tmp_path / "not_a_pack").mkdir()
    assert discover_characters(tmp_path) == {}


def test_a_broken_pack_raises_rather_than_vanishing(tmp_path):
    """Opposite of module discovery's fail-soft: a pack the operator
    put here is meant to work, so a typo must not silently disappear."""
    d = tmp_path / "broken"
    d.mkdir()
    (d / "character.yaml").write_text("schema: character/v1\nkind: banana\n")
    with pytest.raises(CharacterError):
        discover_characters(tmp_path)


def test_builtin_dir_is_inside_the_package():
    """Packaged data — it must ship in a non-editable install."""
    assert BUILTIN_DIR.is_dir()
    assert BUILTIN_DIR.parent.name == "assets"


# ── the preview walk ─────────────────────────────────────────────
#
# The demo path: step through the default character's whole animation.
# Tested headless so CI exercises the same code the window drives — a
# preview nobody tests is a preview that breaks silently.

def test_preview_walks_every_state_of_the_default_character():
    from jaeger_animation.play import character_frames

    c = discover_characters()["emotes"]
    specs = character_frames(c)
    assert len(specs) == len(c.expressions) * len(c.mouth_states) == 18
    cells = [p["cell"] for p, _ in specs]
    assert len(set(cells)) == 18, "two states resolved to the same cell"


def test_preview_is_expression_major():
    """Both mouth states of one face sit together, so a mouth flap is
    visible rather than a slideshow of unrelated faces."""
    from jaeger_animation.play import character_frames

    labels = [lbl for _, lbl in character_frames(
        discover_characters()["emotes"])]
    assert labels[0].split("/")[0] == labels[1].split("/")[0]


def test_preview_runs_headless_and_reports_every_state(capsys):
    from jaeger_animation.play import character_frames, cycle

    c = discover_characters()["emotes"]
    rc = cycle(str(c.asset_path), adapter=c.adapter, width=32, height=32,
               headless=True, frames_spec=character_frames(c))
    out = capsys.readouterr().out
    assert rc == 0
    assert "all ok" in out
    assert "happy/open" in out
    assert "FAILED" not in out


def test_preview_cli_end_to_end():
    """The exact command the operator runs, minus the window."""
    from jaeger_animation.play import main

    assert main(["--character", "emotes", "--cycle",
                 "--size", "32x32", "--headless"]) == 0


def test_unknown_character_is_rejected_by_the_cli():
    from jaeger_animation.play import main

    with pytest.raises(SystemExit) as exc:
        main(["--character", "ghost", "--headless"])
    assert "emotes" in str(exc.value)
