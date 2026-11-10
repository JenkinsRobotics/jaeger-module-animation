<h1 align="center">JaegerAnimation</h1>

<p align="center">
  <em>Universal animation and media playback for JaegerOS — assets and procedural scenes become paced RGBA frames on the bus.</em>
</p>

<p align="center">
  <a href="https://github.com/JenkinsRobotics/jaeger-module-animation/releases"><img src="https://img.shields.io/badge/version-0.3.0-2EA44F?style=for-the-badge" alt="Version"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-Apache--2.0-2EA44F?style=for-the-badge" alt="License"></a>
  <img src="https://img.shields.io/badge/python-3.11+-3776AB?style=for-the-badge&logo=python&logoColor=white" alt="Python 3.11+">
</p>

---

> **Jaeger ecosystem identity**
> ID: `org.jenkinsrobotics.animation.jaeger` · Type: **module** ·
> Slot: `animation` · Kind: `engine` · Implementation: `jaeger`

## What it is

JaegerAnimation is the reusable `animation` capability module for JaegerOS.
It decodes image, bitmap, sprite, GIF, video, procedural-math, and MScript
content into paced RGBA frames and publishes those frames without knowing
which display consumes them.

The engine owns playback mechanism. Applications such as Mochi own policy:
characters, expression names, asset selection, and when an animation should
play. Hardware projects such as JP01 own the final display driver. This keeps
one rendering path usable by a desktop window, an LED matrix, or another
JaegerOS display.

The module pins JaegerOS only and is discovered through the
`jaeger_os.module_roots` entry point. It does not depend on JaegerAI, Mochi,
or a GUI toolkit.

## Contract

- Consumes `/act/display/play` and `/act/display/stop`.
- Produces `/act/display/frame`, `/act/display/state`, and
  `/act/display/stats`.
- Provides `play_animation`, `stop_animation`, and `play_media` tools.
- Claims the stable `animation` slot through `jaeger_animation/module.yaml`.
- Ships strict character-pack loading for application-owned character data.

## Install

```bash
git clone https://github.com/JenkinsRobotics/jaeger-module-animation.git
cd JaegerAnimation
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e ".[bootstrap]"
```

Optional playback dependencies:

```bash
pip install -e ".[gui]"       # PySide6 preview window
pip install -e ".[video]"     # video decoding
```

## Standalone playback

The standalone player exercises the same adapters used by the module:

```bash
python -m jaeger_animation.play image.png --headless
python -m jaeger_animation.play clip.gif --size 256x256
python -m jaeger_animation.play --list-characters
python -m jaeger_animation.play --character emotes --cycle
```

`--headless` renders without opening a display and prints frame statistics,
which makes it suitable for development and CI.

## Application composition

A JaegerOS application selects the provider by slot rather than importing
its rendering engine:

```toml
[[node]]
id = "animation"
slot = "animation"
backend = "thread"
restart = "on_failure"
config_key = "animation"
```

Swapping the animation provider is therefore a composition change, not an
application-code change.

## Layout

```text
jaeger_animation/
├── module.yaml       stable identity, slot, topics, tools, and factory
├── node.py           JaegerOS node and factory
├── adapters/         image, bitmap, sprite, GIF, video, math, MScript
├── characters.py     strict character-pack format and discovery
├── procedural/       reusable procedural rendering support
├── play.py           standalone/headless player
└── tests/            module, adapter, character, and playback tests
```

## Development

```bash
pytest -q
ruff check
```

See [`jaeger_animation/docs/MSCRIPT.md`](jaeger_animation/docs/MSCRIPT.md) for
the motion-script language reference — it is the authoritative spec, and it
lives here because the engine that runs it does.

See [`jaeger_animation/docs/DESIGN.md`](jaeger_animation/docs/DESIGN.md) for
the engine boundary and [`dev/docs/reality/STATUS.md`](dev/docs/reality/STATUS.md)
for current implementation status.

## License

[Apache-2.0](LICENSE) © Jenkins Robotics
