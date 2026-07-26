# Framework needs — catalogued, not built

> JaegerOS gaps this module hit while being built. **Nothing here is
> implemented.** Operator instruction, 2026-07-25: framework changes get
> catalogued, not built — we work solely in JaegerAnimation.
>
> Each entry records what was hit, what the module does instead, and what
> it would cost to fix. The workaround is always the honest one — no
> private side-channels that become a second copy of a truth the contract
> should own.

Status key: **blocking** (module cannot do its job) · **degraded**
(works, with a real limitation) · **cosmetic** (correctness unaffected).

---

## FN-1 — `ModuleSpec` has no `kind:` field · cosmetic

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

---

## FN-2 — no frame topic carries pacing or end-of-clip · degraded

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

**Cost to fix:** two optional fields on `MediaFrame` (additive, no
breaking change), or a dedicated `/sense/animation_frame` topic that
mirrors `MediaFrame` plus pacing. The second is cleaner — see FN-4.

---

## FN-3 — `FrameBuffer` is not a contract type · degraded

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

**Note:** fixing this does *not* require JaegerAI to change. This module
would adopt the contract type and its own copy disappears; JaegerAI can
adopt whenever it chooses.

---

## FN-4 — animation frames ride the media frame topic · cosmetic

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

**Cost to fix:** one constant + one `msgspec.Struct` +
`TOPIC_TO_CLASS` registration. Naturally solved together with FN-2 — a
new `AnimationFrame` topic would carry the pacing fields from the start.

---

## Not gaps (checked, working as designed)

- **Out-of-tree discovery via entry points** — `discover_modules()` finds
  a module installed from its own repo through the
  `jaeger_os.modules` entry-point group. Works; this module relies on it.
- **Per-instance geometry** — passing `width`/`height` through the
  manifest's node config is sufficient. A face's size is a property of
  its display, and the manifest is the right place to say so.
- **No `config:` slice** — this module has no settings-catalog group, and
  declaring one with no matching Pydantic model would be a schema field
  with no validator behind it. Correctly omitted.
