# MochiScript (`.mscript`) — language reference

> **This is the authoritative spec.** It documents what
> `jaeger_animation/procedural/mscript_engine.py` and
> `jaeger_animation/adapters/mscript_adapter.py` actually execute, not
> what an older document said they would. Where the two disagreed, the
> engine was the truth and this file was written from it.
>
> It lives here because the engine lives here. An app that plays motion
> scripts — Mochi does — has an editor for them, not a second copy of
> the language.

A motion script is a **sequence of other assets**: play this bitmap,
wait, play that GIF, run a procedural scene, loop. The script is the
character's; the execution is the engine's. `MScriptAdapter` decodes
nothing itself — it binds each command to a real adapter and pumps
frames from whichever is active.

Line-based, inspired by FANUC teach-pendant programs: ordered steps
with explicit waits and jumps.

---

## 1. File structure

```text
[Header start]
! anything here is informational
[Header end]

[Resources start]
K[1]: 'assets/bitmaps/wink_open.json'
[Resources end]

[Main start]
BITMAP K[1] D[2.0]
[Main end]
```

- Only three section names exist: `Header`, `Resources`, `Main`. They
  are **case-sensitive** — `[main start]` is not recognised and its
  contents are silently skipped.
- Lines beginning with `!` are comments. Blank lines are ignored.
- `Resources` is required by anything that references an asset.
- Text outside a recognised section is ignored, so a trailing
  `[Keyframes start] … [Keyframes end]` block (reserved by the old v2.0
  spec, never implemented) is harmless but does nothing.

---

## 2. Resources

```text
K[id]: 'path/to/asset.ext'
```

The path resolves against the **asset root**, which the caller passes as
`params["asset_root"]`. With no asset root given it defaults to the
script's own grandparent — the layout `assets/mscripts/x.mscript`
implies. Single quotes are required.

Every asset a command names must be declared here, including the `.py`
files that `MATH` runs.

---

## 3. Command lines

```text
COMMAND KEY[value] KEY[value] …
```

The parser takes the first token up to its first `[` as the command
name, upper-cases it, then reads every `KEY[value]` pair on the line
into a dict. That one rule is why `LBL[1]` (a command whose bracket
rides its own token) and `JMP LBL[1]` (a command with an argument)
parse the same way.

A `:name` suffix inside any id bracket is a **comment for the reader**
and is stripped: `K[1:left_eye]` is resource 1, `LBL[2:top]` is label 2.

---

## 4. Asset commands

| Command | Adapter chosen | Notes |
|---|---|---|
| `MATH K[n]` | procedural scene | the `.py` scene runner |
| `BITMAP K[n]` | bitmap | `FG` / `BG` recolour it |
| `SPRITE K[n]` | sprite | `SRC[x,y,w,h]` crops the sheet |
| `MEDIA K[n]` | **by file extension** | the general one |
| `IMAGE K[n]` | image | |
| `GIF K[n]` | gif | |
| `VIDEO K[n]` | video | |
| `MSCRIPT K[n]` | procedural scene | |

`MEDIA` is the one to reach for unless you want to force a decoder;
the others pin the adapter regardless of what the file is.

### Two modes

**Load** — the default. The command opens the asset behind `K[n]`,
makes it the active animation, and plays it.

**Event** — with `EVENT[name]`, the command does *not* reopen anything.
It delivers the event, plus every other argument on the line, to the
animation already running under that `K[n]`. This is how a procedural
scene is driven after it starts:

```text
MATH K[1] D[301.0] FG[0,255,0]      ! start a timer scene
WAIT D[0.1]
MATH K[1] EVENT[start] DUR_M[5]     ! tell that same scene to run 5 min
```

The keyed animation persists, so a later `EVENT` reaches the exact
instance that was started, not a fresh one.

---

## 5. Timing

`D[seconds]` on a command is **how long the script waits after issuing
it** — not the asset's own duration.

```text
D[2.5]      wait 2.5 s after this line
D[auto]     wait for the asset's natural length (GIF / video only)
D[asset]    same as auto
```

`MEDIA` with no `D` at all falls back to `auto`.

`WAIT D[seconds]` waits without issuing anything. Existing scripts pair
every command with a matching `WAIT`; that is belt-and-braces, since
`D` already waits.

---

## 6. Control flow

> **Implemented 2026-08-09.** `LBL` and `JMP` were specified in v2.0 and
> no engine implemented them until now — every motion script written
> before that date runs top to bottom exactly once. Those scripts are
> unaffected: a program with no `LBL` behaves identically.

```text
LBL[id]            mark a position — a label, not an action
LBL[id:name]       the name is a comment
JMP LBL[id]        continue from that label
```

A loop:

```text
[Main start]
LBL[1:blink]
BITMAP K[1] D[0.4]
WAIT D[0.4]
BITMAP K[2] D[0.2]
WAIT D[0.2]
JMP LBL[1]
[Main end]
```

Rules the engine enforces:

- **A loop needs a `WAIT` (or a `D`) inside it.** Jumps are resolved
  within a single `update()` call, so a body with nothing to wait on
  spins without ever returning a frame. The engine allows 64 jumps per
  frame, then logs a warning and stops the script — `update()` runs on
  the render thread, so the alternative is a frozen window.
- **A `JMP` to a label that does not exist is skipped**, with a warning,
  and the rest of the script plays. A typo does not take the
  performance down.
- **Duplicate `LBL[id]` — the first wins**, with a warning. Silently
  rebinding would send the loop to a section nobody wrote.
- Labels are indexed once at parse time, so a jump is a dict lookup
  rather than a scan of the program.

There is no conditional jump. `JMP` is unconditional; a loop ends when
something outside the script stops it.

---

## 7. Argument dictionary

| Key | Example | Meaning |
|---|---|---|
| `D` | `D[5.0]`, `D[auto]` | script wait after this line |
| `K` | `K[1]`, `K[1:name]` | resource / keyframe reference |
| `EVENT` | `EVENT[start]` | deliver to the live keyed animation |
| `LBL` | `LBL[1]` | label id (declare, or `JMP` target) |
| `SRC` | `SRC[0,0,64,64]` | sprite source rectangle |
| `SPD` | `SPD[1.5]` | playback speed multiplier |
| `FIT` | `FIT[fit]` | `fit`→contain, `fill`→cover, `stretch`→fill |
| `LOOP` | `LOOP[0]` | `0`/`false`/`no` are false, anything else true |
| `FG` `BG` `CLR` `CLR2` | `FG[0,255,0]` | colours — parsed to `[r,g,b]` |
| `TXT` `SZ` `X` `Y` `RAD` `DUR` `DUR_M` `CFG` `CLEAR` | | passed through untouched |

Only the four colour keys are converted by the engine. Everything else
arrives as the literal string inside the brackets, so a scene reading
`DUR_M` gets `"5"`, not `5`.

`SPD`, `FIT`, `LOOP` and `BG` are translated to modern adapter
parameters for `MEDIA` / `IMAGE` / `GIF` / `VIDEO`; `SRC` and `FG`/`BG`
for `SPRITE` / `BITMAP`. Any other key rides through to the adapter
under its own name.

`CLEAR`, `STOP` and `END` parse as commands and are accepted, but no
adapter acts on them — they are no-ops kept for old scripts.

---

## 8. Worked example

```text
[Header start]
! Converted from demo_sequence.json
[Header end]

[Resources start]
K[1]: 'assets/bitmaps/wink_open.json'
K[2]: 'assets/gifs/gears.gif'
K[3]: 'characters/Patric/assets/patric_emotes.bmp'
K[4]: 'assets/math/timer.py'
[Resources end]

[Main start]
BITMAP K[1] D[3.0]
WAIT D[3.0]
MEDIA K[2] D[5.0]
WAIT D[5.0]
SPRITE K[3] D[2.0] SRC[469,285,64,64]
WAIT D[2.0]
MATH K[4] D[61.0] FG[0,255,255]
WAIT D[0.1]
MATH K[4] EVENT[start] DUR_M[1]
[Main end]
```

---

## 9. Playing one

```bash
python -m jaeger_animation.play assets/mscripts/demo_sequence.mscript
```

or over the bus, which is what an app does:

```text
/act/display/play   asset_path=…/x.mscript  adapter=mscript
```

## 10. What is deliberately absent

- **No conditionals.** `JMP` is unconditional.
- **No variables, no arithmetic.** Values are literals.
- **No nesting.** `MSCRIPT K[n]` runs a scene, not another script.

Motion scripts sequence assets. Anything that needs to make a decision
belongs in a `MATH` scene, or above the engine entirely.
