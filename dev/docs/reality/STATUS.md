# STATUS — JaegerAnimation

**0.1.0 · 2026-07-26 · the raster engine works; the procedural half does not.**

Ported from Mochi into a standalone JaegerOS module. JaegerAI was not
modified. Framework gaps hit along the way were built on JaegerOS branch
`jaeger-animation` (FN-1..FN-5, all resolved).

## Works — verified, not asserted

- **Raster decoding** — `image` and `gif` render at 8x8, 64x64 and 24x1.
  One asset, any display geometry, which is the property the whole
  design rests on.
- **The node** — `/act/animation` and `/act/media` in; `AnimationFrame`
  (with pacing), `AnimationState`, `AnimationStats`, `MediaFrame`,
  `MediaState` out. No renderer inside, no frame callback.
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
- **31 tests pass.**

## BROKEN — the procedural half

**No MathScript/MScript scene renders. Not one.** ~900 lines of ported
`procedural/` code is unreachable, and this is the half that generalizes
across geometry (a 720p GIF cannot render on a 24x8 strip; a procedural
scene can).

Two independent causes:

1. **Scenes import a package name that does not exist here.** Mochi's 52
   math assets do `from plugin_core.mochi_animations import Animation`;
   JaegerAI's 20 scenes do `from mscript.mochi_animations import ...`.
   This module has neither — the code lives at
   `jaeger_animation.procedural.mochi_animations`.
2. **Two incompatible base classes.** `math_adapter.py` defines its own
   `MathScript` and loads subclasses of it. Every real scene subclasses
   `Animation` from `mochi_animations.py`. The adapter finds nothing and
   raises `no MathScript subclass found`.

Also: `.mscript` files are not in `EXTENSION_MAP`, so they route to
`image` and fail. `mscript_engine.py` was copied but nothing calls it.

## Untested

`sprite`, `bitmap` and `video` adapters construct but no test renders
one. `video` additionally needs the `[video]` extra (`imageio`), never
exercised. The three tools validate their arguments in tests but have
never been called end-to-end through a live runtime bus.

## Not built

- **`assets/` is empty.** The module renders whatever it is handed and
  ships no default face. A bare install has nothing to show.
- **README and `docs/index.html` still carry template placeholders**
  (18 and 46 respectively).
- **Nothing pushed.** All work is local.

## Ready for Mochi?

**For a first cut, yes — with a stated limit.** Mochi's animation-only
milestone needs a face rendered in a window from gif/png assets, and
that path is verified working. It does not need procedural, video, or
the tools.

**As "the universal animation engine", no.** Half of it does not run.
