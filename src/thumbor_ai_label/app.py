"""Application class that installs the always-on label handler and the engine hook.

APP_CLASS = "thumbor_ai_label.app.AiLabelServiceApp"
"""

from __future__ import annotations

from thumbor.app import ThumborServiceApp
from thumbor.handlers.imaging import ImagingHandler
from thumbor.utils import logger

from .config import get_settings
from .engine import AiLabelEngineMixin
from .handler import AiLabelImagingHandler
from .icons import LABEL_STATES

#: Both engine slots Thumbor resolves an image through. ``gif_engine`` is used
#: instead of ``engine`` when USE_GIFSICLE_ENGINE is on and the source is a GIF,
#: so hooking only ``engine`` leaves those images unscanned.
ENGINE_SLOTS = ("engine", "gif_engine")


class AiLabelServiceApp(ThumborServiceApp):
    """Thumbor's app with the imaging handler swapped for the labelling one."""

    def __init__(self, context):
        super().__init__(context)
        self._install_engine_hook(context)
        self._validate(context)

    @staticmethod
    def _install_engine_hook(context):
        """Subclass whatever engines are configured, rather than being one.

        ``ENGINE`` is a single config slot, so a deployment that already runs a
        custom engine could not also label images: setting ``ENGINE`` to ours
        displaced theirs. Building the subclass here composes with any engine
        instead, and needs no ``ENGINE`` line at all.

        Patching the class on the shared ``Importer`` is what makes this reach
        every request: ``ContextHandler.initialize`` builds a fresh ``Context`` per
        request from that importer, and ``ContextImporter`` then constructs the
        engine from whatever class it finds. The instance already hanging off this
        boot-time context is deliberately left alone - it never serves an image.
        """
        importer = getattr(context.modules, "importer", None)
        if importer is None:
            return

        wrapped = []
        try:
            for slot in ENGINE_SLOTS:
                base = getattr(importer, slot, None)
                # Already ours, via ENGINE = "thumbor_ai_label.engine" or a
                # hand-written subclass. Wrapping again would run the scan twice.
                if base is None or issubclass(base, AiLabelEngineMixin):
                    continue
                setattr(
                    importer,
                    slot,
                    type(f"AiLabel{base.__name__}", (AiLabelEngineMixin, base), {}),
                )
                wrapped.append(f"{base.__module__}.{base.__name__}")
        except Exception:
            # Without the hook there is no scan, so nothing is labelled. That is
            # the same failure mode as invalid config, and gets the same treatment:
            # loud, and fatal only under strict errors.
            logger.exception("[AiLabel] could not install the engine hook; nothing will be scanned")
            if getattr(context.config, "AI_LABEL_STRICT_ERRORS", False):
                raise
            return

        # Which engine is hooked is not visible anywhere else, and a wrapped
        # third-party engine looks identical to an unwrapped one from the outside.
        if wrapped:
            logger.info("[AiLabel] engine hook installed on %s", ", ".join(wrapped))
        else:
            logger.info("[AiLabel] engine hook already present; nothing to wrap")

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
            return

        if not settings.detectors:
            logger.warning("[AiLabel] no detectors configured; no labels will be drawn")
            return

        # Narrowing AI_LABEL_DRAW_STATES weakens what the pixels disclose, so it is
        # reported at boot rather than left to be discovered from the output.
        dropped = [state.value for state in LABEL_STATES if state not in settings.draw_states]
        if not settings.draw_states:
            logger.warning(
                "[AiLabel] AI_LABEL_DRAW_STATES is empty; no labels will be drawn and the "
                "/meta/ verdict is the only disclosure"
            )
        elif dropped:
            logger.warning(
                "[AiLabel] AI_LABEL_DRAW_STATES leaves %s unmarked; for those images the "
                "/meta/ disclosure is the only one",
                ",".join(dropped),
            )

        # The icon set is named here because AI_LABEL_ICON_DIR makes "default" mean
        # different artwork on different deployments, and a mark drawn from the wrong
        # directory looks entirely correct in the output.
        logger.info(
            "[AiLabel] ready: detectors=%s policy=%s icon_set=%s draw_states=%s",
            ",".join(d.name for d in settings.detectors),
            settings.policy.value,
            settings.icons.name,
            ",".join(state.value for state in LABEL_STATES if state in settings.draw_states),
        )

    def get_handlers(self):
        handlers = []

        for entry in super().get_handlers():
            if len(entry) >= 2 and entry[1] is ImagingHandler:
                entry = (entry[0], AiLabelImagingHandler, *entry[2:])
            handlers.append(entry)

        return handlers
