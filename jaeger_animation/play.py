"""Standalone player — proof the engine renders, with nothing else installed.

    python -m jaeger_animation.play face.gif
    python -m jaeger_animation.play scene.py --adapter math --size 64x64
    python -m jaeger_animation.play clip.gif --headless

This is the acceptance gate for the module's central claim.  It drives
the adapters **directly** — no bus, no JaegerOS runtime, no AI product —
so if it renders in a venv holding only ``jaeger-os`` and
``jaeger-animation``, the JaegerOS-only pin is real rather than asserted.

The window is **PySide6**, the ecosystem's standard cross-platform GUI
toolkit, and is an OPTIONAL extra (``pip install
"jaeger-animation[gui]"``).  A robot renders frames onto hardware and
must never need a desktop toolkit installed to do it, so ``--headless``
— the path the tests and the acceptance gate use — imports nothing but
the adapters.

GUI/logic separation holds: :func:`render` is toolkit-agnostic and does
the real work; :func:`show` is a thin view over it.  Swapping PySide6
for something else touches one function.
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
         height: int = 320, fps: int = 30, scale: int = 1,
         params: dict | None = None) -> None:
    """Play ``asset`` in a PySide6 window until it ends or is closed.

    ``scale`` nearest-neighbour-magnifies the output, so a 64x64 face is
    actually visible on a Retina display without resampling the engine's
    real output — what you see is the pixels the engine produced.
    """
    try:
        from PySide6.QtCore import Qt, QTimer
        from PySide6.QtGui import QImage, QPixmap
        from PySide6.QtWidgets import QApplication, QLabel
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise SystemExit(
            "the window needs PySide6 (the ecosystem's standard GUI "
            "toolkit):\n"
            "    pip install 'jaeger-animation[gui]'\n"
            "Or use --headless, which needs nothing beyond the engine."
        ) from exc

    key, impl = resolve_adapter(asset, adapter)
    impl.open(asset, width=width, height=height,
              params={"loop": True, **(params or {})})

    app = QApplication.instance() or QApplication([])
    label = QLabel()
    label.setWindowTitle(f"JaegerAnimation — {pathlib.Path(asset).name} [{key}]")
    label.setFixedSize(width * scale, height * scale)
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)

    started = time.perf_counter()
    timer = QTimer()

    def tick() -> None:
        try:
            frame = impl.next_frame(time.perf_counter() - started)
        except Exception as exc:  # noqa: BLE001
            print(f"render error: {type(exc).__name__}: {exc}")
            timer.stop()
            label.close()
            return
        if frame is None:
            timer.stop()
            label.close()
            return
        img = QImage(
            bytes(frame.data), frame.width, frame.height,
            frame.width * 4, QImage.Format.Format_RGBA8888,
        )
        pix = QPixmap.fromImage(img)
        if scale != 1:
            # FastTransformation = nearest neighbour: show the engine's
            # actual pixels, not a smoothed guess at them.
            pix = pix.scaled(
                width * scale, height * scale,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.FastTransformation,
            )
        label.setPixmap(pix)
        timer.start(max(1, frame.duration_ms or int(1000 / fps)))

    timer.setSingleShot(True)
    timer.timeout.connect(tick)
    label.show()
    tick()
    try:
        app.exec()
    finally:
        try:
            impl.close()
        except Exception:  # noqa: BLE001
            pass


def cycle(asset: str, *, adapter: str = "sprite", width: int, height: int,
          grid: tuple[int, int], fps: int = 2, scale: int = 1,
          headless: bool = False) -> int:
    """Walk every cell of a sprite sheet in turn.

    A sprite sheet is a set of stills, so ``show()`` on one renders a
    single frozen frame — which tells you nothing about whether the
    sheet is cut correctly. This steps through all of them, which is how
    you actually SEE a character.
    """
    cols, rows = grid
    total = cols * rows

    if headless:
        ok = True
        for cell in range(total):
            frames = render(asset, adapter=adapter, width=width,
                            height=height, max_frames=1,
                            params={"cell": cell, "grid": grid})
            good = bool(frames) and len(frames[0].data) == width * height * 4
            ok = ok and good
            print(f"cell {cell:2d}/{total - 1}  "
                  f"{'ok' if good else 'FAILED'}")
        print(f"{total} cells  {width}x{height}  "
              f"{'all ok' if ok else 'HAS FAILURES'}")
        return 0 if ok else 1

    try:
        from PySide6.QtCore import Qt, QTimer
        from PySide6.QtGui import QImage, QPixmap
        from PySide6.QtWidgets import QApplication, QLabel
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise SystemExit(
            "the window needs PySide6: pip install 'jaeger-animation[gui]'\n"
            "Or add --headless."
        ) from exc

    app = QApplication.instance() or QApplication([])
    label = QLabel()
    label.setFixedSize(width * scale, height * scale)
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    state = {"cell": 0}

    def tick() -> None:
        cell = state["cell"] % total
        state["cell"] += 1
        _, impl = resolve_adapter(asset, adapter)
        try:
            impl.open(asset, width=width, height=height,
                      params={"cell": cell, "grid": grid})
            frame = impl.next_frame(0.0)
        finally:
            try:
                impl.close()
            except Exception:  # noqa: BLE001
                pass
        if frame is None:
            return
        label.setWindowTitle(
            f"{pathlib.Path(asset).name} — cell {cell}/{total - 1}")
        img = QImage(bytes(frame.data), frame.width, frame.height,
                     frame.width * 4, QImage.Format.Format_RGBA8888)
        pix = QPixmap.fromImage(img)
        if scale != 1:
            pix = pix.scaled(width * scale, height * scale,
                             Qt.AspectRatioMode.KeepAspectRatio,
                             Qt.TransformationMode.FastTransformation)
        label.setPixmap(pix)

    timer = QTimer()
    timer.timeout.connect(tick)
    label.show()
    tick()
    timer.start(max(1, int(1000 / max(1, fps))))
    app.exec()
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="python -m jaeger_animation.play",
        description="Render an asset through the animation engine.",
    )
    ap.add_argument("asset", help="path to an image/gif/video/sprite/scene")
    ap.add_argument("--adapter", default=None,
                    help=f"one of {sorted(ADAPTERS)} (default: by extension)")
    ap.add_argument("--cell", type=int, default=None,
                    help="sprite sheets: which cell to show (needs --grid)")
    ap.add_argument("--grid", default=None, metavar="COLSxROWS",
                    help="sprite sheets: sheet layout, e.g. 9x2")
    ap.add_argument("--cycle", action="store_true",
                    help="sprite sheets: walk every cell in turn, so one "
                         "run shows the whole character")
    ap.add_argument("--size", default="480x320", metavar="WxH")
    ap.add_argument("--fps", type=int, default=30,
                    help="fallback pacing when the adapter reports none")
    ap.add_argument("--frames", type=int, default=120,
                    help="max frames to render in --headless")
    ap.add_argument("--scale", type=int, default=1,
                    help="magnify the window NxN (nearest neighbour) so a "
                         "64x64 face is visible; does not resample output")
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

    params: dict = {}
    if args.grid:
        try:
            c_str, _, r_str = args.grid.partition("x")
            params["grid"] = (int(c_str), int(r_str))
        except ValueError:
            raise SystemExit(f"--grid must look like 9x2, got {args.grid!r}")
    if args.cell is not None:
        params["cell"] = args.cell

    if args.cycle:
        if "grid" not in params:
            raise SystemExit("--cycle needs --grid, e.g. --grid 9x2")
        return cycle(args.asset, adapter=args.adapter or "sprite",
                     width=width, height=height, grid=params["grid"],
                     fps=args.fps, scale=max(1, args.scale),
                     headless=args.headless)

    if args.headless:
        frames = render(args.asset, adapter=args.adapter, width=width,
                        height=height, max_frames=args.frames, params=params)
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
         fps=args.fps, scale=max(1, args.scale), params=params)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
