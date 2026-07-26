# JaegerAnimation — design

> **Status:** 0.1.0, built 2026-07-25. The engine renders and the node
> publishes; see `dev/docs/reality/STATUS.md` for what is proven vs
> planned.

## What this is

The **universal animation engine** for the Jaeger ecosystem. It turns
assets and procedural scenes into RGBA frames and publishes them on the
bus. It is an engine-module sibling to JaegerKokoroTTS and
JaegerWhisperSTT, and follows the same rules.

**It pins JaegerOS only — never JaegerAI.** A robot body has to be able
to show a face with no AI product installed. Enforced structurally by
`tests/test_module_contract.py`, which parses every import.

## The one property everything rests on

**The engine's job ends at frames on a topic.**

```
/act/animation      ─┐                    ┌─▶ /sense/media_frame
/act/animation_stop ─┼─▶  AnimationNode  ─┼─▶ /sense/animation_state
/act/media          ─┘                    └─▶ /sense/media_state
                                │
        ┌───────────────────────┼───────────────────────┐
        ▼                       ▼                       ▼
  window renderer        avc01_driver              web canvas
  (Mochi)                → FM[hex] serial          (future)
                         (JP01, unchanged)
```

There is no renderer inside this module, and no frame callback. Every
sink is a subscriber. That single property is what lets one engine drive
a virtual companion on a Mac and a physical robot's LED face without
either forking it.

Rendering happens centrally on the host; pixels are transmitted to
whatever displays them. A display device stays a display device.

## Persona-free by construction

The command vocabulary is *"play this asset at this geometry"*, never
*"be happy"*. Emotion-to-asset mapping is **character data**, owned by
whatever consumes this module. `tools: []` in `module.yaml` is honest,
not unfinished: an agent-facing `set_avatar_state` would have to know
what "happy" means, and this engine deliberately does not.

## Geometry

Adapters take `width`/`height` at `open()`, so they decode straight to
the target size. This is why procedural rendering matters as much as
decoding: a 720p GIF cannot meaningfully render on a 24×8 LED strip, but
an MScript scene renders at whatever size it is handed.

A node instance has one geometry, set from the manifest — a face's size
is a property of its display. A unit with two displays instantiates the
module twice, the pattern JP01 already uses for `camera_node` and
`videorx_node`.

## What came from Mochi

Ported from `~/GITHUB/Mochi/mochi/` (Apache-2.0), where this engine grew
up. Mochi's layout was already clean — one copy of each decoder.

| From Mochi | Here |
|---|---|
| `nodes/media/frames.py` | `frames.py` — `FrameBuffer` |
| `nodes/animation/base.py` | `base.py` — `AnimationAdapter` Protocol |
| `nodes/media/decoders/*` | `adapters/` — image, gif, sprite, bitmap, video |
| `nodes/animation/adapters/math_adapter.py` | `adapters/math_adapter.py` |
| `nodes/animation/plugin_core/*` | `procedural/` — MScript engine, gfx, font, colour |
| `nodes/animation/node.py` | `node.py` — rewritten to publish frames |

### Deliberately left behind

| Left in Mochi | Why |
|---|---|
| `auto_state.py` | Subscribes to TTS topics. In here it would make animation implicitly require a TTS module — the coupling JaegerOS's 0.9 AEC seam exists to prevent. |
| `bridge.py` | A WebSocket renderer. Renderers are sinks; sinks are subscribers, owned by the consumer. |
| `llm_command_parser.py` | Product concern. |
| Character assets | Character content belongs in a character pack, not a framework-tier module. |

## Relationship to Anima Studio — no dependency, ever

[Anima Studio](https://github.com/JenkinsRobotics/AnimaStudio) is a
**separate, independently developed project** for authoring avatar rigs
and characters. It targets its own Swift app and ESP32 firmware, so it
can never depend on JaegerOS. The two projects are peers.

```
Anima Studio  →  character pack  →  JaegerAnimation  →  Mochi / JP01
  (authoring)     (the contract)      (the runtime)      (the projects)
```

**The character pack is the only contract between them**, and its format
will be standardized jointly as both projects develop. Neither imports
the other — enforced by the same structural test that bans `jaeger_ai`.

Worth knowing when standardizing that format: Anima Studio's
`animacore/raster/` independently ported the *same* Mochi decoders
(commit `9c9ef63`, 2026-07-24). That is a deliberate two-implementation
strategy, not accidental duplication — two real runtimes is the
strongest test a format can get. It is **not** a reason to pin, merge, or
share code.

## Known limitations

Recorded honestly rather than worked around. Full detail in
[`dev/docs/FRAMEWORK_NEEDS.md`](../../dev/docs/FRAMEWORK_NEEDS.md).

- **Frame pacing is not expressible on the bus** (FN-2). `MediaFrame`
  carries no `duration_ms`/`is_final`, so a bus subscriber must guess a
  frame rate. The player is unaffected because it drives adapters
  directly.
- **`FrameBuffer` is this module's own copy** (FN-3) — the type belongs
  in the contract; there are three copies ecosystem-wide.
- **No `kind:` in the manifest** (FN-1) — `ModuleSpec` does not validate
  the field yet, so this module's kind (`processing`) is a comment.
- **Animation frames ride the media frame topic** (FN-4) — the contract
  has no animation frame topic.

Separately, a pre-existing JP01 constraint worth knowing when planning a
physical face: a 64×64 `FM[hex]` frame is 24,576 ASCII chars, which at
115200 baud is ~2 s/frame. The engine can render far faster than that
wire can carry. Not caused by this module and not its to fix.

## Proving it works

The acceptance gate is the standalone player running in a venv that holds
**only** `jaeger-os` and `jaeger-animation`:

```bash
python -m jaeger_animation.play face.gif --headless   # frame count + RGBA check
python -m jaeger_animation.play face.gif              # a window, for your eyes
```

If it needs anything beyond `jaeger-os`, the pin is broken.
