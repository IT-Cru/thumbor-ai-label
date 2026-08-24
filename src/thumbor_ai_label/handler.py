"""Always-on wiring: label every request without touching any URL.

Thumbor has no native "always run this filter" hook, so the plugin supplies one by
wrapping the per-request filters factory. Every request gets the label filter
appended to its post-transform phase, whether or not the URL asked for it.

Appending rather than prepending is deliberate: the label is drawn *after* any
other post-transform filter, so a URL cannot blur, desaturate or overlay it away.
"""

from __future__ import annotations

from thumbor.filters import PHASE_POST_TRANSFORM
from thumbor.handlers.imaging import ImagingHandler
from thumbor.utils import logger

from .filters.ai_label import Filter as AiLabelFilter


class AlwaysOnFiltersFactory:
    """Wraps Thumbor's FiltersFactory and appends the label filter to every request."""

    def __init__(self, inner, filter_cls=AiLabelFilter):
        self._inner = inner
        self._filter_cls = filter_cls
        # pre_compile builds the class-level regex that init_if_valid needs, and
        # returns the filter's URL name. It is idempotent.
        self._name = filter_cls.pre_compile()
        self._phase = getattr(filter_cls, "phase", PHASE_POST_TRANSFORM)

        # Also make the filter addressable by name, so an explicit ai_label() in a
        # URL still resolves even when it is absent from FILTERS.
        filters_map = getattr(inner, "filter_classes_map", None)
        if filters_map is not None and self._name:
            filters_map.setdefault(self._name, filter_cls)

    def create_instances(self, context, filter_params):
        runner = self._inner.create_instances(context, filter_params)

        try:
            instance = self._filter_cls.init_if_valid("{}()".format(self._name), context)
            if instance is not None:
                runner.filter_instances[self._phase].append(instance)
            else:
                logger.error("[AiLabel] could not instantiate the label filter")
        except Exception:  # pylint: disable=broad-except
            # A failure here must not cost the user their image; it costs the label,
            # loudly. The engine-level draw guard means a duplicate append would be
            # harmless anyway.
            logger.exception("[AiLabel] failed to attach the always-on label filter")

        return runner

    def __getattr__(self, name):
        # Anything else on the factory keeps working untouched.
        return getattr(self._inner, name)


class AiLabelImagingHandler(ImagingHandler):
    """ImagingHandler that labels every image it serves."""

    def initialize(self, context):
        super().initialize(context)
        # self.context is the fresh per-request Context built by super(), and its
        # filters_factory is per-Context too, so wrapping here affects exactly this
        # request and cannot leak into another.
        self.context.filters_factory = AlwaysOnFiltersFactory(
            self.context.filters_factory
        )
