# STATUS — JaegerAnimation

**0.1.0 · 2026-07-25 · the engine renders and the node publishes.**

Built by porting Mochi's animation/media engine into a standalone
JaegerOS module. JaegerAI and JaegerOS were not modified — framework gaps
were catalogued in [`../FRAMEWORK_NEEDS.md`](../FRAMEWORK_NEEDS.md)
instead of built.

## Proven

- **6 adapters render** — image, gif, sprite, bitmap, video, math
  (procedural/MScript). Verified at 8x8, 64x64 and 24x1: one asset, any
  display geometry.
- **The node publishes on the bus** — `/act/animation` and `/act/media`
  in, `MediaFrame` + `AnimationState`/`MediaState` out. No frame
  callback, no renderer inside the module.
- **The JaegerOS-only pin is real, not asserted** — a venv holding ONLY
  `jaeger-os` + `jaeger-animation` (no `jaeger_ai`, no `mochi`, no
  `animacore`) renders frames and passes the full suite.
- **Discovery binds the slot** — `discover_modules()` finds this module
  through the `jaeger_os.module_roots` entry point and resolves its
  factory, without JaegerOS ever naming it.
- **26/26 tests pass**, including a structural import audit that parses
  every source file.

## Not built (planned)

- **Character packs** — the format is standardized jointly with Anima
  Studio; no pack code ships until it has a validator.
- **Default face assets** — `assets/` is empty. The module renders any
  asset it is handed; it ships none of its own yet.
- **Mochi integration** — the first consumer. Separate effort.

## Known limitations

Detailed in [`../FRAMEWORK_NEEDS.md`](../FRAMEWORK_NEEDS.md): frame
pacing is not expressible on the bus (FN-2), `FrameBuffer` is this
module's own copy rather than a contract type (FN-3), `kind:` cannot be
declared (FN-1), and animation frames share the media frame topic (FN-4).
