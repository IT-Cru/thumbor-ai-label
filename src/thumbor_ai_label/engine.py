"""Engine hook: capture provenance metadata from the original bytes.

``BaseEngine.load(buffer, extension)`` is the one point in Thumbor's request flow
that always sees the original file. Both fetch paths converge on it - a storage
hit loads the cached original, and a storage miss loads what the loader returned -
so hooking here needs no assumptions about which loader or storage backend is in
use, and works whether or not the source was cached.

Only the scan runs here, because ``load`` is synchronous. Detectors run later in
the filter, which is async and can therefore accommodate a detector that calls out
to another system.

Normally nothing here is configured. ``AiLabelServiceApp`` builds the subclass at
boot from whichever engines are configured, so the hook composes with a custom
engine rather than displacing it, and covers ``GIF_ENGINE`` as well.

``Engine`` below exists for the one case the app cannot serve: a deployment that
does not set ``APP_CLASS`` and instead adds ``ai_label()`` to its URL rules by
hand. That needs a scan without an app to install one::

    ENGINE = "thumbor_ai_label.engine"

Setting it alongside ``APP_CLASS`` is harmless - the app skips a slot that already
has the mixin. If you run a custom engine *and* the filter-only setup, subclass it
yourself and point ``ENGINE`` at that::

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
    """Thumbor's PIL engine with provenance scanning attached.

    For ``ENGINE = "thumbor_ai_label.engine"``. With ``APP_CLASS`` set, the app
    wraps the configured engine instead and this class is not needed.
    """
