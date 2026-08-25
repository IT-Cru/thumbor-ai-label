"""Application class that installs the always-on label handler.

    APP_CLASS = "thumbor_ai_label.app.AiLabelServiceApp"
"""

from __future__ import annotations

from thumbor.app import ThumborServiceApp
from thumbor.handlers.imaging import ImagingHandler
from thumbor.utils import logger

from .config import get_settings
from .handler import AiLabelImagingHandler


class AiLabelServiceApp(ThumborServiceApp):
    """Thumbor's app with the imaging handler swapped for the labelling one."""

    def __init__(self, context):
        super().__init__(context)
        self._validate(context)

    @staticmethod
    def _validate(context):
        """Resolve settings at boot so bad config surfaces now, not per request.

        Icon paths, detector names and enum values are all validated here. Without
        this the first sign of a typo would be images quietly going out unlabelled.
        """
        try:
            settings = get_settings(context.config)
        except Exception:
            logger.exception("[AiLabel] configuration is invalid; labelling will not work")
            if getattr(context.config, "AI_LABEL_STRICT_ERRORS", False):
                raise
            return

        if not settings.enabled:
            logger.warning("[AiLabel] AI_LABEL_ENABLED is False; no labels will be drawn")
        elif not settings.detectors:
            logger.warning("[AiLabel] no detectors configured; no labels will be drawn")
        else:
            logger.info(
                "[AiLabel] ready: detectors=%s policy=%s",
                ",".join(d.name for d in settings.detectors),
                settings.policy.value,
            )

    def get_handlers(self):
        handlers = []

        for entry in super().get_handlers():
            if len(entry) >= 2 and entry[1] is ImagingHandler:
                entry = (entry[0], AiLabelImagingHandler, *entry[2:])
            handlers.append(entry)

        return handlers
