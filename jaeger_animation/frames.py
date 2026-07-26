"""FrameBuffer — re-exported from the JaegerOS contract.

The type is contract-tier (``jaeger_os.contract.topics.FrameBuffer``)
because every animation module produces it and the bus and every
renderer have to agree on one shape. This module used to define its own
copy, which made it the third in the ecosystem — exactly the "two copies
of one truth" failure CONVENTIONS.md law 1 warns about.

Kept as a module so the adapters' ``from ..frames import FrameBuffer``
imports stay put, and so there is one obvious place to look for where
the frame format is defined.
"""

from __future__ import annotations

from jaeger_os.contract.topics import FrameBuffer

__all__ = ["FrameBuffer"]
