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
    """ModuleSpec sets forbid_unknown_fields=True — this catches a field
    the framework does not know about (e.g. `kind:`, still planned)."""
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
        ("MediaFrame", "/sense/media_frame"),
        ("MediaState", "/sense/media_state"),
        ("AnimationState", "/sense/animation_state"),
    ):
        assert f"topics.{symbol}(" in src, f"node never publishes {symbol}"
        assert topic in MANIFEST["produces"], f"{topic} missing from manifest"


def test_tools_are_honestly_empty() -> None:
    """No tools is a deliberate call, not an oversight: driving a face
    from an agent means mapping emotion -> asset, which is character data
    owned by the consumer, not by a persona-free engine."""
    assert MANIFEST["tools"] == []
