"""Entry-point target for JaegerOS's ``discover_modules()`` out-of-tree seam.

Registered under the ``jaeger_os.module_roots`` entry-point group (see
this repo's ``pyproject.toml``) so JaegerOS finds this module WITHOUT
ever importing or naming ``jaeger_animation`` — the framework only knows
the group name, never the contributor.

This repo ships ONE module and its ``module.yaml`` sits at the package
root, so the root IS the module (the singleton shape ``discover_modules``
documents, same as the Mind's). Contrast JaegerKokoroTTS, which returns
``<pkg>/nodes`` — a directory whose *children* are modules — because it
is laid out to hold more than one.
"""

import pathlib

_HERE = pathlib.Path(__file__).resolve().parent


def roots() -> tuple[pathlib.Path, ...]:
    return (_HERE,)
