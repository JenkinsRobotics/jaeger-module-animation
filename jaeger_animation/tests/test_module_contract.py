"""The module's contract with the ecosystem.

These tests guard the properties that make this a *module* rather than a
folder of code: what it may import, what its manifest promises, and that
the manifest matches the package.
"""

from __future__ import annotations

import ast
import importlib.util
import pathlib

import pytest
import yaml

PACKAGE = pathlib.Path(__file__).resolve().parents[1]
MANIFEST = yaml.safe_load((PACKAGE / "module.yaml").read_text())


def _source_files() -> list[pathlib.Path]:
    return [p for p in PACKAGE.rglob("*.py") if "tests" not in p.parts]


# ── the pin ──────────────────────────────────────────────────────

FORBIDDEN = {
    # The whole point: a robot body must show a face with no AI product.
    "jaeger_ai": "JaegerAI — this module pins JaegerOS ONLY",
    # Ported FROM Mochi; must never depend back on it.
    "mochi": "Mochi — sources were ported, not referenced",
    # Anima Studio is a peer project. The character pack is the only
    # contract between us; never a code dependency, in either direction.
    "animacore": "AnimaCore — Anima Studio is a peer, not a dependency",
}


@pytest.mark.parametrize("forbidden,why", sorted(FORBIDDEN.items()))
def test_never_imports(forbidden: str, why: str) -> None:
    """Structural, not aspirational: parse every import statement."""
    offenders: list[str] = []
    for path in _source_files():
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            for name in names:
                if name == forbidden or name.startswith(f"{forbidden}."):
                    offenders.append(f"{path.name}:{node.lineno}")
    assert not offenders, f"{why}; found in {offenders}"


def test_only_framework_tier_jaeger_import() -> None:
    """The only jaeger_* package this module may import is jaeger_os."""
    seen: set[str] = set()
    for path in _source_files():
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            mods: list[str] = []
            if isinstance(node, ast.Import):
                mods = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                mods = [node.module or ""]
            seen.update(m.split(".")[0] for m in mods
                        if m.startswith("jaeger"))
    assert seen <= {"jaeger_os", "jaeger_animation"}, (
        f"unexpected jaeger-tier imports: {seen}"
    )


# ── the manifest ─────────────────────────────────────────────────

def test_manifest_identity() -> None:
    assert MANIFEST["module"] == "animation"
    assert MANIFEST["slot"] == "animation"
    assert MANIFEST["factory"].startswith("jaeger_animation:")


def test_manifest_factory_resolves() -> None:
    """A factory string that doesn't import is a manifest that lies."""
    dotted, _, attr = MANIFEST["factory"].partition(":")
    mod = importlib.import_module(dotted)
    assert callable(getattr(mod, attr))


def test_manifest_validates_against_installed_jaeger_os() -> None:
    """ModuleSpec sets forbid_unknown_fields=True — this catches any
    field the installed framework does not know about."""
    from jaeger_os.contract.modules import ModuleSpec

    import msgspec
    msgspec.convert(MANIFEST, ModuleSpec)


def test_declared_libraries_are_importable() -> None:
    for lib in MANIFEST.get("requires_libraries", []):
        assert importlib.util.find_spec(lib) is not None, (
            f"module.yaml declares {lib!r} but it is not importable"
        )


def test_declared_topics_exist_in_the_contract() -> None:
    """Every topic named in the manifest must be a real contract topic —
    a typo here binds a node to a topic nothing publishes."""
    from jaeger_os.transport import topics

    declared = set(MANIFEST["consumes"]) | set(MANIFEST["produces"])
    assert declared <= set(topics.ALL_TOPICS), (
        f"not in the contract: {declared - set(topics.ALL_TOPICS)}"
    )


def test_produced_topics_match_what_the_node_publishes() -> None:
    """The manifest is the one copy of this truth (CONVENTIONS law 1),
    so it must not drift from the code."""
    src = (PACKAGE / "node.py").read_text()
    for symbol, topic in (
        ("DisplayFrame", "/act/display/frame"),
        ("DisplayState", "/act/display/state"),
        ("DisplayStats", "/act/display/stats"),
        ("DisplayFrame", "/act/display/frame"),
        ("DisplayState", "/act/display/state"),
    ):
        assert f"topics.{symbol}(" in src, f"node never publishes {symbol}"
        assert topic in MANIFEST["produces"], f"{topic} missing from manifest"


# ── the three declared surfaces ──────────────────────────────────
#
# A module declares topics (general I/O), tools (agentic I/O), and a
# config slice — the pattern kokoro_tts and whisper_stt already ship.
# These pin the manifest to the implementations so they cannot drift.

def test_declared_tools_exist_and_match():
    """module.yaml's tools: is the one copy of this truth."""
    from jaeger_animation.tools import TOOLS

    assert set(MANIFEST["tools"]) == set(TOOLS), (
        f"manifest {MANIFEST['tools']} vs implemented {sorted(TOOLS)}"
    )
    for name, fn in TOOLS.items():
        assert callable(fn), name
        assert fn.__doc__, f"{name} has no docstring — an agent reads it"


def test_tools_are_persona_free():
    """The mechanism, not the policy. An emotion->asset table is
    character data owned by the consumer, never by this engine."""
    from jaeger_animation import tools

    src = pathlib.Path(tools.__file__).read_text().lower()
    for word in ("happy", "sad", "angry", "emotion="):
        assert f"def {word}" not in src
    assert "set_avatar_state" not in MANIFEST["tools"]


def test_tools_validate_input_before_touching_the_bus():
    """A tool is called by a model, so bad arguments are expected
    traffic, not exceptional — they must return a reason, not raise."""
    from jaeger_animation.tools import play_animation, play_media

    r = play_animation(asset_path="")
    assert r["ok"] is False and "required" in r["reason"]

    r = play_animation(asset_path="x.gif", adapter="nonexistent")
    assert r["ok"] is False and "unknown adapter" in r["reason"]

    r = play_media(path="")
    assert r["ok"] is False and "required" in r["reason"]


def test_config_slice_matches_the_manifest():
    from jaeger_animation.config import AnimationConfig

    assert MANIFEST["config"] == "animation"
    cfg = AnimationConfig()
    assert cfg.width > 0 and cfg.height > 0
    with pytest.raises(Exception):
        AnimationConfig(nonsense=1)  # extra="forbid" typo guard


def test_kind_is_declared_and_legal():
    from jaeger_os.contract.modules import MODULE_KINDS

    assert MANIFEST["kind"] == "processing"
    assert MANIFEST["kind"] in MODULE_KINDS


def test_telemetry_topic_is_separate_from_frames():
    """Monitoring whether a face keeps up must not require subscribing
    to its full pixel stream."""
    from jaeger_os.transport import topics

    assert topics.ACT_DISPLAY_STATS in MANIFEST["produces"]
    assert topics.ACT_DISPLAY_FRAME in MANIFEST["produces"]
