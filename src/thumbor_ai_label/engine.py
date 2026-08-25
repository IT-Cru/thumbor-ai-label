"""Engine hook: capture provenance metadata from the original bytes.

``BaseEngine.load(buffer, extension)`` is the one point in Thumbor's request flow
that always sees the original file. Both fetch paths converge on it - a storage
hit loads the cached original, and a storage miss loads what the loader returned -
so hooking here needs no assumptions about which loader or storage backend is in
use, and works whether or not the source was cached.

Only the scan runs here, because ``load`` is synchronous. Detectors run later in
the filter, which is async and can therefore accommodate a detector that calls out
to another system.

If you run an engine other than PIL, build your own::

    from thumbor_ai_label.engine import AiLabelEngineMixin
    from my.engine import Engine as Base

    class Engine(AiLabelEngineMixin, Base):
        pass
"""

from __future__ import annotations

from thumbor.engines.pil import Engine as PilEngine
from thumbor.utils import logger

from .scan import scan
from .state import store_scan


class AiLabelEngineMixin:
    """Scans the original buffer for provenance metadata as the image is loaded."""

    def load(self, buffer, extension):
        super().load(buffer, extension)

        try:
            if not self.context.config.AI_LABEL_ENABLED:
                return
            store_scan(self.context, scan(buffer))
        except Exception:  # noqa: BLE001
            # Never let provenance scanning break image loading. Without a stored
            # scan the filter simply has nothing to work from, and the configured
            # policy decides what that means.
            logger.exception("[AiLabel] failed to scan source metadata")


class Engine(AiLabelEngineMixin, PilEngine):
    """Thumbor's PIL engine with provenance scanning attached."""
