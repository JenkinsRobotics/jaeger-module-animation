# STATUS — JaegerAnimation

**0.1.0 · 2026-07-26 · all six adapters render; ships a character.**

Ported from Mochi into a standalone JaegerOS module. JaegerAI was not
modified. Framework gaps hit along the way were built on JaegerOS branch
`jaeger-animation` (FN-1..FN-5, all resolved).

## Works — verified, not asserted

- **All seven adapter types render** — `image` (incl. `.bmp`), `gif`, `sprite`,
  `bitmap` (1-bit JSON), `math` (procedural scenes), `video` (with the
  `[video]` extra), plus `mscript` sequences. Verified at 8x8, 64x64 and 24x1: one asset, any
  display geometry, which is the property the whole design rests on.
- **The node** — `/act/display/play` and `/act/display/play` in; `DisplayFrame`
  (with pacing), `DisplayState`, `DisplayStats`, `DisplayFrame`,
  `DisplayState` out. No renderer inside, no frame callback.
- **Three declared surfaces** — topics, tools (`play_animation`,
  `stop_animation`, `play_media`), and a `config:` slice, matching what
  `kokoro_tts` and `whisper_stt` ship.
- **The JaegerOS-only pin** — a venv holding only `jaeger-os` +
  `jaeger-animation` renders frames, binds the slot, and passes the
  suite. `jaeger_ai`, `mochi`, `animacore` absent, enforced by an
  import-parsing test.
- **Discovery** — `discover_modules()` binds `slot: animation` through
  the `jaeger_os.module_roots` entry point.
- **The player** — `python -m jaeger_animation.play`, headless or a
  PySide6 window.
- **Character packs** — a self-contained folder with a `character.yaml`
  declaring what it is and how to run it, the same shape as a module one
  tier down. This is the format Anima Studio exports and this engine
  consumes; the loader is strict and names the offending file. Persona
  lives in the pack: the engine hardcodes no expression names, it reads
  the character's own vocabulary.
- **The `emotes` demo character** — nine emotions x two mouth states on a
  9x2 atlas. Column selects emotion, row selects open (talking) or closed
  (idle), so alternating rows on one column is a mouth flap. All 18
  states render at 64x64, 128x128 and 480x320.
- **The preview walk** — `play --character emotes --cycle` steps through
  every named expression in a window; `--headless` runs the same code
  path, so the demo is tested rather than merely available.
- **Sprite grid addressing** — `params={"cell": n, "grid": (cols, rows)}`,
  so a caller picks frame 12 of an evenly-cut sheet without pixel
  arithmetic. `src` rects still work for irregular atlases.
- **105 tests pass.**

## Fixed since the first audit

Three of six adapters were broken, each for a different reason, and all
three looked fine because the suite only asserted adapters could be
*constructed*:

- **`bitmap`** — extension routing sent `.bmp` to it, but it renders
  1-bit packed monochrome from JSON. It was `json.loads()`-ing binary.
  `.bmp` is an image; `.json` is a bitmap.
- **`math`** — every real scene subclasses `Animation` and imports
  `plugin_core.*` (Mochi) or `mscript.*` (JaegerAI); the adapter looked
  for a `MathScript` base no content had heard of. It now accepts both
  lineages and resolves those import names during scene load, scoped so
  they never leak into `sys.modules`.
- **`video`** — a missing optional codec raised a bare
  `ModuleNotFoundError`. It now names the extra.

Also: a scene that raises now raises. Returning `None` was
indistinguishable from "clip ended", which is how a scene that never
rendered looked like one that finished.

**There is now a render test per adapter, plus a guard that fails if a
new adapter arrives without one.** Constructing an adapter proves
nothing; that is what let three broken ones ship.

## Motion scripts

`.mscript` sequences other assets (`MATH K[1] D[11.0] FG[...]`) rather
than producing pixels itself. `MScriptAdapter` plays one by binding each
command to a real adapter and pumping frames from whichever is active —
composition, not a second engine (a test asserts it contains no decoder).

The reasoning: a character supplies motion scripts, or a caller sends a
list of commands, and the node executes the sequence. The script is
character content and playing content is this module's job. (Contrast
`/act/timeline/run`, which coordinates animation WITH tts and motor — that
is cross-module orchestration and still belongs to the consumer.)

Verified against Mochi's real scripts: 6/6 play. One (`eyes.py`, via
`demo_math_eyes_sequence`) needs >=64px width — a scene assuming a
minimum size, not an engine fault; the engine raises naming the failure
rather than rendering nothing.

## Not built

- **README and `docs/index.html` still carry template placeholders**
  (18 and 46 respectively).
- **Nothing pushed.** All work is local.

## Ready for Mochi?

**For a first cut, yes — with a stated limit.** Mochi's animation-only
milestone needs a face rendered in a window from gif/png assets, and
that path is verified working. It does not need procedural, video, or
the tools.

**As "the universal animation engine", no.** Half of it does not run.
