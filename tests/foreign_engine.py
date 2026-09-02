"""A stand-in for a third-party engine, e.g. thumbor-video-engine.

Exists to prove the plugin composes with an engine it has never heard of, rather
than displacing it in the single ``ENGINE`` slot.
"""

from __future__ import annotations

from thumbor.engines.pil import Engine as PilEngine

#: Appended to by every load, so a test can assert this engine actually ran.
loads_seen: list[int] = []


class Engine(PilEngine):
    def load(self, buffer, extension):
        loads_seen.append(len(buffer or b""))
        return super().load(buffer, extension)
