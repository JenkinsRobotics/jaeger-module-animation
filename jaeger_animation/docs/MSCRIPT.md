# MochiScript (`.mscript`) — language reference

> **The authoritative spec.** Written from the parsers, not from an
> older document: where the two disagreed, the code was the truth.
> It lives beside the engine that executes it, because a spec kept next
> to the scripts rather than next to the parser is a spec nobody updates
> when the parser changes.
>
> Last verified against the code: **2026-08-15**.

Line-based, in the lineage of FANUC teach-pendant programs: declared
sections, ordered steps, explicit waits, labels and jumps. A `.LS`
listing and a `.mscript` are the same idea — a program a person can read
in a text editor, with its data blocks alongside it.

---

## 1. What a motion script is

A **performance**: a sequence of assets, expressions, speech and waits
that makes a character do something. At its simplest it plays one clip
after another. At its fullest it drives several channels at once while a
program beside them waits for a person to answer.

---

## 2. Two readers, and which one runs what

This is the first thing to understand, because the language is executed
by two different things on purpose.

| | reads | runs |
|---|---|---|
| **The engine** — `procedural/mscript_engine.py` | `[Main]` | asset commands: `MEDIA`, `BITMAP`, `SPRITE`, `MATH`, plus `WAIT`, `LBL`, `JMP` |
| **The conductor** — an app (Mochi: `core/scenes.py`, `core/staging.py`) | `[Main]` **and** `[Track_*]` | everything above, plus `FACE`, `SAY`, `LISTEN`, `ASK`, `CUE`, `LIGHT`, `SERVO` |

**Why the split.** The engine's job ends at frames on a topic — it
renders. Making it publish speech, drive servos or wait on a microphone
would break the one rule it has. So an app that owns a voice and a bus
conducts, and the engine stays a renderer.

**Both recognise every section.** The engine skips tracks deliberately
rather than by accident, so one document means the same thing to both
readers instead of losing half its content in one of them. An unknown
section is an **error** in both.

---

## 3. File structure

```text
[Header start]
! Bitmap Man — telling a secret.
[Header end]

[Resources start]
K[1]: 'characters/bitmap man/assets/faces/neutral_blink.json'
[Resources end]

[Main start]
BITMAP K[1] D[2.0]
[Main end]
```

The section vocabulary is **declared and closed**, and has been since
v2.0. That rigidity is the point: a name outside the set is a typo, and
a parser that quietly accepts one drops a whole block of somebody's
script in silence. Extending the language means adding to the set on
purpose, **in every reader**.

| Section | Holds |
|---|---|
| `[Header …]` | informational metadata, `!` comments |
| `[Resources …]` | asset declarations — required by anything using `K[n]` |
| `[Keyframes …]` | reserved since v2.0. See §5 |
| `[Main …]` | the sequential program |
| `[Track_<channel> …]` | one channel on a clock. See §9 |

Names are **case-sensitive**. Lines beginning with `!` are comments;
blank lines are ignored. Text before the first section is a preamble and
is kept but not executed.

---

## 4. Resources

```text
K[id]: 'path/to/asset.ext'
```

Every asset a command names is declared here, including the `.py` files
`MATH` runs. Single quotes are required.

Paths resolve against the **asset root**, passed by the caller as
`params["asset_root"]`. With none given it defaults to the script's own
grandparent — the layout `assets/mscripts/x.mscript` implies. An app
with character packs passes its project root instead, so a script inside
`characters/<id>/mscripts/` still resolves project-relative paths.

---

## 5. Keyframes — reserved, and what it is for

`[Keyframes]` has been in the spec since v2.0 and no parser has ever
read it. It is the slot for **structured data**, and FANUC's `/POS`
block is the shape it wants:

```text
/POS
P[1]{
   GP1:
    UF : 1, UT : 1,
    X = 504.893 mm, Y = 80.248 mm, Z = -277.487 mm,
    W = 177.984 deg, P = -1.249 deg, R = 95.663 deg
};
```

A named entry with typed fields, referenced from the program by number
(`L P[4] 500mm/sec FINE`). `[Resources]` is the flat version of the same
idea — an id pointing at one value.

For an animatronic the natural content is **poses**: a named set of
joint positions a track can call up by number, rather than inlining
angles on every line.

> **Status: not implemented.** Documented here so the slot's purpose is
> recorded rather than rediscovered. A parser that reads it must be
> added to both readers at once.

---

## 6. Command lines

```text
COMMAND KEY[value] KEY[value] …
```

The parser takes the first token up to its first `[` as the command
name, upper-cases it, then reads every `KEY[value]` pair **on the whole
line** into a dict. That one rule is why `LBL[1]` — a command whose
bracket rides its own token — and `JMP LBL[1]` — a command with an
argument — parse identically.

A `:name` suffix inside any id bracket is a **comment for the reader**
and is stripped: `K[1:left_eye]` is resource 1, `LBL[2:top]` is label 2.

---

## 7. Command reference — the engine

Asset commands. Each opens the asset behind `K[n]` and plays it.

| Command | Adapter | Notes |
|---|---|---|
| `MEDIA K[n]` | **by file extension** | the general one; reach for this |
| `IMAGE K[n]` | image | |
| `GIF K[n]` | gif | |
| `VIDEO K[n]` | video | |
| `BITMAP K[n]` | bitmap | `FG` / `BG` recolour it |
| `SPRITE K[n]` | sprite | `SRC[x,y,w,h]` crops the sheet |
| `MATH K[n]` | procedural scene | runs a `.py` scene |
| `MSCRIPT K[n]` | procedural scene | |

Accepted and ignored, kept for old scripts: `CLEAR`, `STOP`, `END`.

### Event mode

With `EVENT[name]` a command does **not** reopen anything. It delivers
the event, plus every other argument on the line, to the animation
already running under that `K[n]`:

```text
MATH K[1] D[301.0] FG[0,255,0]      ! start a timer scene
WAIT D[0.1]
MATH K[1] EVENT[start] DUR_M[5]     ! tell THAT scene to run 5 minutes
```

The keyed animation persists, so a later `EVENT` reaches the exact
instance that was started, not a fresh one.

---

## 8. Command reference — the performance tier

Run by a conducting app, not the engine. Mochi implements all of these.

| Command | Does |
|---|---|
| `FACE EXPR[happy] D[1.5]` | show an expression from the character's **own** vocabulary, so one script suits any pack declaring the same faces. `D` holds it |
| `SAY TXT['…'] VOICE[bm_george]` | speak, and **wait for the done-ack** before continuing. `VOICE` overrides the character's own |
| `LISTEN D[10]` | hold until a person answers, or time out. The one step whose length the audience chooses |
| `ASK D[25]` | hand what was just heard to the mind and speak its reply — the improvised beat in an authored script |
| `CUE SRC['path.mscript']` | run another script as a nested cue (track use) |
| `LIGHT CLR[40,30,80]` | a colour on a light channel |
| `SERVO JOINT[neck_pan] POS[-20]` | a joint position |

`LIGHT` and `SERVO` have **no node behind them yet**. They are still
scheduled, so a show authored ahead of the hardware keeps correct time
on the channels that do exist — the normal case for an animatronic,
where the show is written before the figure is wired.

---

## 9. Tracks — channels on a clock

```text
[Track_eyes start]
FACE EXPR[neutral]   T[0.0]
FACE EXPR[look_up]   T[0.9]
[Track_eyes end]

[Track_voice start]
SAY TXT['Can you keep a secret?'] T[0.6]
[Track_voice end]

[Track_motion start]
SERVO JOINT[neck_pan] POS[-20] T[1.2] D[1.0]
[Track_motion end]
```

`T[seconds]` is **absolute from the track's start**. A track says
*when*; `[Main]` says *what comes next*. That is the whole difference,
and it is why a figure can look around **while** it talks — something a
program counter cannot express, because it does one thing at a time.

The channel is taken from the section name: `Track_eyes` and
`Track_face` are animation, `Track_voice` speech, `Track_light`,
`Track_motion`, `Track_sound`, `Track_cue`. An unrecognised suffix is a
label, not an error — it falls back to animation.

---

## 10. Show files — both at once

A file may hold `[Main]` **and** tracks. They start together from the
same `t=0`, which is the animatronic shape: the figure moves and speaks
on the clock while a program beside it can branch, loop and stop for a
person.

```text
[Track_voice start]
SAY TXT['Welcome. Let me show you what I can do at once.'] T[0.4]
[Track_voice end]

[Main start]
WAIT D[8.5]
SAY TXT['Now the clock is done. Say something and I will wait.']
LISTEN D[12]
ASK D[25]
[Main end]
```

Neither shape alone is a show: a clock cannot wait for a person, and a
program counter cannot overlap.

---

## 11. Timing

`D[seconds]` is **how long the script waits after issuing a line** — not
the asset's own length.

```text
D[2.5]      wait 2.5 s after this line
D[auto]     wait for the asset's natural length (GIF / video only)
D[asset]    same as auto
```

`MEDIA` with no `D` falls back to `auto`. `WAIT D[s]` waits without
issuing anything.

Inside a `[Track_*]`, `D` is a **duration** rather than a delay — the
clip's own length — because a track's ordering comes from `T`.

---

## 12. Control flow

> `LBL` / `JMP` were specified in v2.0 and no engine implemented them
> until **2026-08-09**. Scripts written before that date are unaffected:
> a program with no `LBL` behaves identically.

```text
LBL[id]          mark a position — a label, not an action
LBL[id:name]     the name is a comment
JMP LBL[id]      continue from that label
```

```text
[Main start]
LBL[1:blink]
BITMAP K[1] D[0.4]
BITMAP K[2] D[0.2]
JMP LBL[1]
[Main end]
```

Rules both readers enforce:

- **A loop needs a `WAIT`, a `D`, a `SAY` or a `LISTEN` in it.** Jumps
  resolve within one `update()`, so a body with nothing to wait on spins
  without ever returning a frame. After 64 jumps the script stops with a
  warning — `update()` runs on the render thread, so the alternative is
  a frozen window.
- **A `JMP` to a missing label is skipped**, with a warning, and the
  rest plays. A typo does not take the performance down.
- **Duplicate `LBL[id]`: the first wins**, with a warning. Silently
  rebinding sends the loop somewhere nobody wrote.
- Labels are indexed once at parse time, so a jump is a dict lookup.

`JMP` is **unconditional**. See §15.

---

## 13. Argument dictionary

| Key | Example | Meaning |
|---|---|---|
| `D` | `D[5.0]`, `D[auto]` | wait after this line; duration inside a track |
| `T` | `T[1.2]` | absolute time within a track, in seconds |
| `K` | `K[1]`, `K[1:name]` | resource reference |
| `EXPR` | `EXPR[happy]` | a character expression |
| `TXT` | `TXT['hello']` | a string |
| `VOICE` | `VOICE[bm_george]` | override the character's voice |
| `SRC` | `SRC[0,0,64,64]` | sprite rect; or a path for `CUE` |
| `EVENT` | `EVENT[start]` | deliver to the live keyed animation |
| `LBL` | `LBL[1]` | label id |
| `JOINT` `POS` | `JOINT[neck_pan] POS[-20]` | a servo target |
| `CLR` | `CLR[40,30,80]` | a light colour |
| `SPD` | `SPD[1.5]` | playback speed |
| `FIT` | `FIT[fit]` | `fit`→contain, `fill`→cover, `stretch`→fill |
| `LOOP` | `LOOP[0]` | `0`/`false`/`no` are false |
| `FG` `BG` `CLR2` | `FG[0,255,0]` | colours — parsed to `[r,g,b]` |
| `SZ` `X` `Y` `RAD` `DUR` `DUR_M` `CFG` `CLEAR` | | passed through untouched |

Only the colour keys are converted by the engine. Everything else
arrives as the literal string inside the brackets — a scene reading
`DUR_M` gets `"5"`, not `5`.

---

## 14. Playing one

```bash
python -m jaeger_animation.play characters/x/mscripts/blink.mscript
```

Over the bus, which is what an app does:

```text
/act/display/play   asset_path=…/x.mscript  adapter=mscript
```

In Mochi: **Stage → Performances** runs a script; **Scenes** plays a
compiled timeline; the **MScript Editor** opens either as text or as a
node graph.

---

## 15. Not implemented

Recorded so the gaps are known rather than rediscovered.

- **No conditionals.** `JMP` is unconditional. FANUC's shape is the
  intended one: `IF DI[3] = ON, JMP LBL[1]`, with `DO[n]`, `DI[n]` and
  `R[n]` as the register/IO vocabulary.
- **No registers, variables or arithmetic.** Values are literals.
- **`[Keyframes]` is unread.** See §5.
- **No typed header.** FANUC's `/ATTR` carries `OWNER`, `COMMENT`,
  `CREATE`, `MODIFIED`; `[Header]` is free-text comments only.
- **No motion termination type.** FANUC's `FINE` (stop exactly) versus
  `CNT` (blend through) is the difference between a mechanical stop and
  a natural one, and belongs on a `SERVO` line.
- **A track cannot wait.** A `LISTEN` inside `[Main]` stops for a
  person; the clock does not stop with it, so other tracks carry on and
  sync is lost after. Choosing per cue — hold the transport, or let it
  drift — is undecided.
