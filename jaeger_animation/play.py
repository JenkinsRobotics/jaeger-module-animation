"""Standalone player — proof the engine renders, with nothing else installed.

    python -m jaeger_animation.play face.gif
    python -m jaeger_animation.play scene.py --adapter math --size 64x64
    python -m jaeger_animation.play clip.gif --headless

This is the acceptance gate for the module's central claim.  It drives
the adapters **directly** — no bus, no JaegerOS runtime, no AI product —
so if it renders in a venv holding only ``jaeger-os`` and
``jaeger-animation``, the JaegerOS-only pin is real rather than asserted.

The window uses ``tkinter`` (stdlib) and PIL (already a hard dependency),
so the player adds no dependency of its own.  Mochi's own player
(``interfaces/v4/mochi_vdisplay_player_qt.py``, 579 lines of PySide6 +
ZMQ overlay) was deliberately not ported: this one only has to prove the
engine works.
"""

from __future__ import annotations

import argparse
import pathlib
import time

from .adapters import ADAPTERS, adapter_for_path
from .frames import FrameBuffer

_DEFAULT_FRAME_MS = 33


def resolve_adapter(asset: str, name: str | None = None):
    """Return ``(key, adapter_instance)`` for ``asset``.

    An explicit ``name`` always wins — sprite sheets are ``.png`` files
    and cannot be told from plain images by extension alone.
    """
    key = name or adapter_for_path(asset)
    cls = ADAPTERS.get(key)
    if cls is None:
        raise SystemExit(
            f"unknown adapter {key!r}; choose from {sorted(ADAPTERS)}"
        )
    return key, cls()


def render(asset: str, *, adapter: str | None = None, width: int = 480,
           height: int = 320, max_frames: int = 120,
           params: dict | None = None) -> list[FrameBuffer]:
    """Render up to ``max_frames`` frames and return them.

    Draws nothing to a screen — this is the headless path the tests use,
    and the one that proves decoding works independently of any display.
    """
    _, impl = resolve_adapter(asset, adapter)
    impl.open(asset, width=width, height=height, params=dict(params or {}))
    frames: list[FrameBuffer] = []
    try:
        t = 0.0
        for _ in range(max_frames):
            frame = impl.next_frame(t)
            if frame is None:
                break
            frames.append(frame)
            t += (frame.duration_ms or _DEFAULT_FRAME_MS) / 1000.0
            if frame.is_final:
                break
    finally:
        try:
            impl.close()
        except Exception:  # noqa: BLE001
            pass
    return frames


def show(asset: str, *, adapter: str | None = None, width: int = 480,
         height: int = 320, fps: int = 30) -> None:
    """Play ``asset`` in a window until it ends or the window closes."""
    import tkinter as tk

    from PIL import Image, ImageTk

    key, impl = resolve_adapter(asset, adapter)
    impl.open(asset, width=width, height=height, params={"loop": True})

    root = tk.Tk()
    root.title(f"JaegerAnimation — {pathlib.Path(asset).name} [{key}]")
    label = tk.Label(root, borderwidth=0, highlightthickness=0)
    label.pack()
    root.bind("<Escape>", lambda _e: root.destroy())

    started = time.perf_counter()

    def tick() -> None:
        try:
            frame = impl.next_frame(time.perf_counter() - started)
        except Exception as exc:  # noqa: BLE001
            print(f"render error: {type(exc).__name__}: {exc}")
            root.destroy()
            return
        if frame is None:
            root.destroy()
            return
        img = Image.frombytes(
            "RGBA", (frame.width, frame.height), bytes(frame.data))
        photo = ImageTk.PhotoImage(img)
        label.configure(image=photo)
        # Tk garbage-collects the image unless a reference is held on the
        # widget; without this the window renders blank.
        label.image = photo  # type: ignore[attr-defined]
        root.after(max(1, frame.duration_ms or int(1000 / fps)), tick)

    root.after(0, tick)
    try:
        root.mainloop()
    finally:
        try:
            impl.close()
        except Exception:  # noqa: BLE001
            pass


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="python -m jaeger_animation.play",
        description="Render an asset through the animation engine.",
    )
    ap.add_argument("asset", help="path to an image/gif/video/sprite/scene")
    ap.add_argument("--adapter", default=None,
                    help=f"one of {sorted(ADAPTERS)} (default: by extension)")
    ap.add_argument("--size", default="480x320", metavar="WxH")
    ap.add_argument("--fps", type=int, default=30,
                    help="fallback pacing when the adapter reports none")
    ap.add_argument("--frames", type=int, default=120,
                    help="max frames to render in --headless")
    ap.add_argument("--headless", action="store_true",
                    help="render without a window; print frame stats")
    args = ap.parse_args(argv)

    try:
        w_str, _, h_str = args.size.partition("x")
        width, height = int(w_str), int(h_str)
    except ValueError:
        raise SystemExit(f"--size must look like 640x480, got {args.size!r}")

    if not pathlib.Path(args.asset).exists():
        raise SystemExit(f"asset not found: {args.asset}")

    if args.headless:
        frames = render(args.asset, adapter=args.adapter, width=width,
                        height=height, max_frames=args.frames)
        if not frames:
            print("0 frames — the adapter produced nothing")
            return 1
        total_ms = sum(f.duration_ms for f in frames)
        expected = width * height * 4
        ok = all(len(f.data) == expected for f in frames)
        print(f"{len(frames)} frames  {width}x{height}  {total_ms} ms  "
              f"RGBA={'ok' if ok else 'MISMATCH'}")
        return 0 if ok else 1

    show(args.asset, adapter=args.adapter, width=width, height=height,
         fps=args.fps)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
