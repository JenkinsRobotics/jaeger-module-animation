# Framework needs — catalogued, not built

> JaegerOS gaps this module hit while being built.
>
> Each entry records what was hit, what the module did instead, and what
> it cost to fix. The workaround is always the honest one — no private
> side-channels that become a second copy of a truth the contract should
> own.

**FN-1 through FN-4 are RESOLVED** — built on JaegerOS branch
`jaeger-animation` (commit `d1fd56f`) after the operator lifted the
catalogue-only instruction on 2026-07-26. They are kept here, not
deleted, because the reasoning is the record of *why* those contract
types exist. **FN-5 is open.**

| | Gap | Status |
|---|---|---|
| FN-1 | `ModuleSpec.kind` | ✅ built |
| FN-2 | frame pacing on the bus | ✅ built (`AnimationFrame`) |
| FN-3 | `FrameBuffer` as a contract type | ✅ built |
| FN-4 | animation frames need their own topic | ✅ built |
| FN-5 | discovery swallows a contributor's ImportError | ⬜ open |

Status key: **blocking** (module cannot do its job) · **degraded**
(works, with a real limitation) · **cosmetic** (correctness unaffected).

---

## FN-1 — `ModuleSpec` has no `kind:` field · cosmetic · ✅ RESOLVED

**Hit at:** `jaeger_animation/module.yaml`

`Jaeger-Template`'s `TAXONOMY.md` defines four module kinds
(`driver` / `processing` / `engine` / `mind`) as the ownership axis —
orthogonal to `slot`, which says what role a module fills. This module is
`kind: processing`: software-only, touches topics, never devices.

But `ModuleSpec` (`jaeger_os/contract/modules.py`) sets
`forbid_unknown_fields=True` and has no `kind` field, so declaring it
fails strict discovery. The template says so itself:

> PLANNED FIELD: … setting this on a REAL module.yaml today will fail
> strict discovery until the schema ships it.

**What this module does instead:** declares its kind in a `module.yaml`
comment. Not a field, so nothing can read it.

**Cost to fix:** one optional field on `ModuleSpec` plus a validator for
the four legal values. Contract-tier — needs sign-off per
`CONVENTIONS.md`.

**Why it matters beyond cosmetics:** the taxonomy exists so the framework
can eventually enforce "nothing outside a `driver`-kind module may open a
device." That rule cannot be enforced against a comment.

**Resolved:** `ModuleSpec.kind` added, defaulting empty so every existing
manifest keeps validating, with `MODULE_KINDS` checked at load time so a
bad value names the offending file. This module now declares
`kind: processing`.

---

## FN-2 — no frame topic carries pacing or end-of-clip · degraded · ✅ RESOLVED

**Hit at:** `jaeger_animation/node.py::_publish_frame`

`MediaFrame` (the only frame topic in the 0.9 contract) carries
`data`, `width`, `height`. It has no field for:

- **`duration_ms`** — how long this frame should stay visible
- **`is_final`** — whether the clip just ended

The engine's own `FrameBuffer` has both, because a decoder genuinely
knows them: a GIF's inter-frame delays vary within one file. They are
dropped at the bus boundary.

**Consequence:** a subscriber cannot pace playback from the bus alone. It
must guess a frame rate, or infer the end of a clip from the separate
`/sense/media_state` topic — which is a different message with no
ordering guarantee relative to the frames it describes.

**What this module does instead:** publishes `MediaFrame` and drops the
two fields. The standalone player (`play.py`) drives adapters directly,
so it is unaffected — which is exactly why the gap is easy to miss until
a real bus consumer needs it.

**Who this will bite:** JP01's `avc01_driver`, re-encoding frames to
`FM[hex]` for the LED matrix, and any Mochi window renderer that wants
correct GIF timing.

**Resolved:** the second option — `/sense/animation_frame` carries
`duration_ms` and `is_final`, and the envelope's `seq` lets a consumer
detect drops. The node publishes it; the module contract test pins it.

---

## FN-3 — `FrameBuffer` is not a contract type · degraded · ✅ RESOLVED

**Hit at:** `jaeger_animation/frames.py`

Every producer of frames defines its own `FrameBuffer`. Counted
2026-07-25:

| Copy | Location |
|---|---|
| 1 | `jaeger_ai/nodes/animation/base.py` |
| 2 | `jaeger_ai/nodes/media/frames.py` |
| 3 | `jaeger_animation/frames.py` (this module) |

Copies 1 and 2 live in the same package and are why four decoders
(`bitmap`, `gif`, `image`, `sprite`) exist there twice — byte-identical
except for which `FrameBuffer` they import. That is ~585 duplicated lines
caused by nothing but a missing shared type.

This is `CONVENTIONS.md` law 1 ("two copies of one truth") at ecosystem
scale.

**What this module does instead:** ships its own copy, ported from
Mochi. Correct in isolation; it does make this the third.

**Cost to fix:** move the dataclass into `jaeger_os/contract/` and have
producers import it. It imports nothing, so it cannot violate the
contract package's no-inward-imports rule. Contract-tier — needs
sign-off.

**Resolved:** the dataclass now lives in `jaeger_os.contract.topics`.
`jaeger_animation/frames.py` is a re-export, so copy 3 is gone. JaegerAI
still has copies 1 and 2 and can adopt whenever it chooses — no change
was required there, by design.

---

## FN-4 — animation frames ride the media frame topic · cosmetic · ✅ RESOLVED

**Hit at:** `jaeger_animation/module.yaml` `produces:`

The contract has `/act/animation` and `/sense/animation_state` but **no
animation frame topic** — animation state has a topic, animation pixels
do not. So rendered frames go out on `/sense/media_frame` regardless of
which intent produced them.

**Consequence:** a subscriber that only wants the face must filter frames
by something other than topic, or accept movie frames too. The two
intents are distinguishable on the command and state topics but not on
the frame topic.

**What this module does instead:** publishes every frame on
`/sense/media_frame`, and keeps the intents distinct on the state topics
(`/sense/animation_state` vs `/sense/media_state`).

**Resolved together with FN-2.** `/act/animation` frames now go to
`/sense/animation_frame` and `/act/media` frames to `/sense/media_frame`,
so a renderer showing the face is never handed a movie.

---

## FN-5 — discovery swallows a contributor's ImportError · degraded

**Hit at:** the clean-venv gate, 2026-07-26.

`jaeger_animation` failed to import (a missing transitive dependency).
`discover_modules()` returned `{}` with **no message of any kind** — the
module simply was not there, and `KeyError: 'animation'` at the call site
was the only symptom. The cause took a manual `import jaeger_animation`
to find.

The fail-soft is deliberate and mostly right (`_external_module_roots`:
*"one bad contributor, not fatal"*) — a package that is not installed
must not take down discovery for everyone else. But an **installed**
contributor whose entry point raises is a different case: that is a
broken install, and it is invisible.

Note the asymmetry: a malformed `module.yaml` inside a discovered root
raises loudly, by design. An `ImportError` reaching the same root does
not.

**Cost to fix:** log the exception at WARNING in
`_external_module_roots`'s `except`. Two lines. Optionally surface it in
`jaeger doctor` as "installed but not loadable", which is exactly the
class of failure an operator cannot otherwise diagnose.

---

## Not gaps (checked, working as designed)

- **Out-of-tree discovery via entry points** — `discover_modules()` finds
  a module installed from its own repo through the
  `jaeger_os.module_roots` entry-point group (the group takes a callable
  returning roots; see `module_roots.py`). Works; this module relies on
  it. See FN-5 for how it fails when the contributor cannot import.
- **Per-instance geometry** — passing `width`/`height` through the
  manifest's node config is sufficient. A face's size is a property of
  its display, and the manifest is the right place to say so.

**Corrected 2026-07-26:** this file previously listed "no `config:`
slice" as *correctly omitted*, and the module shipped `tools: []`. Both
were wrong, and neither was a framework gap — the three-surface
convention (topics · tools · config) already shipped in 0.9 and both
sibling engine modules follow it. `kokoro_tts` declares
`text_to_speech` + `config: kokoro_tts`; `whisper_stt` declares `listen`
+ `config: whisper_stt`. This module now declares
`play_animation`/`stop_animation`/`play_media` + `config: animation`.
