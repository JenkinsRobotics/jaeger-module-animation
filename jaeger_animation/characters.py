"""Character packs — a self-contained folder the engine can play.

The same shape as a module, one tier down: a folder carrying its assets
plus one `character.yaml` declaring what it is and everything needed to
run it. Drop the folder in, and a runtime plays it without being told
anything else.

    characters/
      emotes/
        character.yaml     ← the manifest
        emotes.png         ← the asset
        emotes.props.yaml  ← per-asset properties (optional)

**This is the contract with Anima Studio** — the format it exports and
this engine consumes, standardized jointly as both develop. Neither
project imports the other; the pack is the only thing that crosses.

**Where persona lives.** The engine hardcodes no expression names. A
character declares its own vocabulary (`happy`, `unamused`, whatever it
wants) and how each maps to pixels; the engine reads that mapping and
renders. Swap the pack, get a different character, change no code. That
is what keeps the engine persona-free while still being able to play a
persona.

Loading is STRICT and names the offending file, matching how JaegerOS
loads `module.yaml`: a broken pack must fail loudly, not render the
wrong face.
"""

from __future__ import annotations

import pathlib
from dataclasses import dataclass, field
from typing import Any

SCHEMA = "character/v1"

#: How a character is drawn — determines which adapter plays it.
KINDS = frozenset({"sprite_sheet", "clip_set", "procedural", "rig"})

#: Characters shipped with this module.
BUILTIN_DIR = pathlib.Path(__file__).resolve().parent / "assets" / "characters"


class CharacterError(ValueError):
    """A pack is malformed. Always names the file."""


@dataclass(frozen=True)
class Character:
    """A loaded, validated character pack."""

    name: str
    root: pathlib.Path
    kind: str
    display_name: str = ""
    version: str = "0.0.0"
    description: str = ""
    render: dict[str, Any] = field(default_factory=dict)
    expressions: dict[str, dict] = field(default_factory=dict)
    mouth_states: dict[str, int] = field(default_factory=dict)
    default_expression: str = ""
    default_mouth: str = ""

    # ── what a runtime actually needs ────────────────────────────

    @property
    def asset_path(self) -> pathlib.Path:
        """Absolute path to this character's asset."""
        return self.root / self.render["asset"]

    @property
    def adapter(self) -> str:
        return self.render["adapter"]

    @property
    def grid(self) -> tuple[int, int] | None:
        g = self.render.get("grid")
        return (int(g[0]), int(g[1])) if g else None

    def play_params(self, expression: str = "",
                    mouth: str = "") -> dict[str, Any]:
        """Adapter params to render ``expression`` in ``mouth`` state.

        Falls back to the pack's declared defaults, so a caller that
        knows nothing about this character can still show its face.
        """
        expr = expression or self.default_expression
        state = mouth or self.default_mouth
        if expr not in self.expressions:
            raise CharacterError(
                f"{self.name}: unknown expression {expr!r}; "
                f"has {sorted(self.expressions)}"
            )
        if self.kind != "sprite_sheet":
            # Only the sprite path is implemented. Say so rather than
            # returning params that quietly render nothing.
            raise CharacterError(
                f"{self.name}: kind {self.kind!r} is declared but this "
                f"engine only plays 'sprite_sheet' today"
            )
        if state and state not in self.mouth_states:
            raise CharacterError(
                f"{self.name}: unknown mouth state {state!r}; "
                f"has {sorted(self.mouth_states)}"
            )
        cols, _rows = self.grid  # validated non-None for sprite_sheet
        column = int(self.expressions[expr]["column"])
        row = int(self.mouth_states.get(state, 0))
        return {"cell": row * cols + column, "grid": self.grid}


def load_character(root: pathlib.Path | str) -> Character:
    """Parse + validate ``<root>/character.yaml``."""
    import yaml

    root = pathlib.Path(root)
    path = root / "character.yaml"
    if not path.is_file():
        raise FileNotFoundError(f"no character.yaml at {path}")
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}

    def need(key: str) -> Any:
        if key not in raw:
            raise CharacterError(f"{path}: missing required key {key!r}")
        return raw[key]

    if raw.get("schema") != SCHEMA:
        raise CharacterError(
            f"{path}: schema must be {SCHEMA!r}, got {raw.get('schema')!r}")

    kind = need("kind")
    if kind not in KINDS:
        raise CharacterError(
            f"{path}: kind {kind!r} is not one of {sorted(KINDS)}")

    render = need("render")
    for key in ("adapter", "asset"):
        if not render.get(key):
            raise CharacterError(f"{path}: render.{key} is required")
    asset = root / render["asset"]
    if not asset.is_file():
        raise CharacterError(
            f"{path}: render.asset {render['asset']!r} does not exist "
            f"at {asset}")

    expressions = raw.get("expressions") or {}
    if not expressions:
        raise CharacterError(f"{path}: at least one expression is required")

    char = Character(
        name=need("character"),
        root=root,
        kind=kind,
        display_name=raw.get("name", ""),
        version=str(raw.get("version", "0.0.0")),
        description=raw.get("description", ""),
        render=render,
        expressions=expressions,
        mouth_states=raw.get("mouth_states") or {},
        default_expression=raw.get("default_expression", ""),
        default_mouth=raw.get("default_mouth", ""),
    )

    if kind == "sprite_sheet":
        if char.grid is None:
            raise CharacterError(
                f"{path}: a sprite_sheet needs render.grid = [cols, rows]")
        cols, rows = char.grid
        for expr, spec in expressions.items():
            col = spec.get("column")
            if col is None or not 0 <= int(col) < cols:
                raise CharacterError(
                    f"{path}: expression {expr!r} column {col!r} is outside "
                    f"the {cols}x{rows} grid")
        for state, row in char.mouth_states.items():
            if not 0 <= int(row) < rows:
                raise CharacterError(
                    f"{path}: mouth state {state!r} row {row!r} is outside "
                    f"the {cols}x{rows} grid")

    if char.default_expression and char.default_expression not in expressions:
        raise CharacterError(
            f"{path}: default_expression {char.default_expression!r} is not "
            f"a declared expression")
    if char.default_mouth and char.default_mouth not in char.mouth_states:
        raise CharacterError(
            f"{path}: default_mouth {char.default_mouth!r} is not a declared "
            f"mouth state")
    return char


def discover_characters(
    roots: pathlib.Path | tuple[pathlib.Path, ...] | None = None,
) -> dict[str, Character]:
    """Find every character pack under ``roots``, keyed by name.

    Defaults to this module's built-ins. Mirrors JaegerOS's
    ``discover_modules()``: a directory without a manifest is skipped
    silently (not every folder is a pack), but a directory WITH a broken
    one raises — a malformed pack must fail loudly, not vanish.
    """
    if roots is None:
        roots = (BUILTIN_DIR,)
    elif isinstance(roots, (str, pathlib.Path)):
        roots = (pathlib.Path(roots),)

    found: dict[str, Character] = {}
    for root in roots:
        root = pathlib.Path(root)
        if not root.is_dir():
            continue
        candidates = ([root] if (root / "character.yaml").is_file()
                      else sorted(p for p in root.iterdir() if p.is_dir()))
        for d in candidates:
            if not (d / "character.yaml").is_file():
                continue
            char = load_character(d)
            found[char.name] = char
    return found


__all__ = [
    "SCHEMA", "KINDS", "BUILTIN_DIR",
    "Character", "CharacterError",
    "load_character", "discover_characters",
]
