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

from . import meta
from .compose import can_draw_on
from .filters.ai_label import Filter as AiLabelFilter
from .label import apply as apply_label
from .label import decide_for_request


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
            instance = self._filter_cls.init_if_valid(f"{self._name}()", context)
            if instance is not None:
                runner.filter_instances[self._phase].append(instance)
            else:
                logger.error("[AiLabel] could not instantiate the label filter")
        except Exception:  # noqa: BLE001
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
        self.context.filters_factory = AlwaysOnFiltersFactory(self.context.filters_factory)

    async def after_transform(self):
        # Both steps run before super(), not after. ``BaseHandler.after_transform``
        # ends in ``finish_request()``, which assembles and sends the response - so
        # anything done afterwards arrives after the payload it belongs in.
        await self._ensure_verdict()
        await self._label_if_thumbor_skips_the_phase()
        await super().after_transform()

    def _thumbor_skips_post_transform(self) -> bool:
        """Whether Thumbor is about to skip the phase the label filter lives in.

        ``BaseHandler.after_transform`` guards ``apply_filters(PHASE_POST_TRANSFORM)``
        with ``extension != ".gif" or USE_GIFSICLE_ENGINE is None``. That setting
        defaults to ``False``, not ``None``, so the guard is false for **every** GIF
        on **every** engine and no post-transform filter runs at all - which is why
        no GIF has ever carried a label.

        Mirrored rather than imported because Thumbor exposes no hook for it. If
        Thumbor ever stops skipping the phase for GIFs, nothing here draws twice -
        its filter run finds the engine already marked - but this pre-draw should be
        deleted rather than left in place, because a label drawn *before* the phase
        can be blurred away by another filter in it, and being drawn last is the
        whole point of appending the filter.
        """
        request = getattr(self.context, "request", None)
        return (
            getattr(request, "extension", None) == ".gif"
            and self.context.config.USE_GIFSICLE_ENGINE is not None
        )

    async def _label_if_thumbor_skips_the_phase(self):
        """Draw the label ourselves for a request whose filters Thumbor skips.

        Only *this* label, never the whole phase. Running ``apply_filters`` here
        would silently turn on every other post-transform filter for GIFs - a URL's
        ``filters:blur()`` would start applying where it never has - and that is not
        this plugin's decision to make.
        """
        if not self._thumbor_skips_post_transform():
            return

        request = getattr(self.context, "request", None)
        if getattr(request, "meta", False):
            # A /meta/ response is JSON; there are no pixels to mark. ``draw`` says
            # the same and would no-op, but stopping here keeps the frame walk off
            # the JSONEngine wrapping the real one.
            return

        engine = getattr(request, "engine", None)
        if engine is None:
            return

        for target in self._drawable_engines(engine):
            await apply_label(self.context, target)

    @staticmethod
    def _drawable_engines(engine):
        """Every engine that contributes pixels to the output.

        An animated GIF is read back through ``frame_engines()``, so a label pasted
        onto ``engine.image`` alone is thrown away - the output carries nothing at
        all. ``BaseFilter.run`` handles this for a filter that runs normally; this
        does the same for the one that never gets to.

        ``can_draw_on`` is checked first, and not only as an optimisation.
        ``thumbor.engines.gif.Engine`` reports ``is_multiple()`` as
        ``frame_count > 1`` but never sets ``multiple_engine``, which only the PIL
        path assigns - so asking it for ``frame_engines()`` would raise. It has no
        PIL image to draw on either way, and ``label.apply`` says so once.
        """
        if can_draw_on(engine) and engine.is_multiple():
            return engine.frame_engines()
        return [engine]

    async def _ensure_verdict(self):
        """Make sure a /meta/ response has a verdict to report.

        ``_load_results`` runs in Thumbor's worker thread and cannot await, so the
        verdict has to exist before the response is assembled. ``decide_for_request``
        is memoised, so this costs nothing when the label filter already ran.

        For a **GIF this is the only place a verdict is produced at all.**
        ``BaseHandler.after_transform`` guards the whole post-transform phase with
        ``extension != ".gif" or USE_GIFSICLE_ENGINE is None``, and that setting
        defaults to ``False`` rather than ``None`` - so for any GIF, on any engine,
        no post-transform filter runs and the label filter never fires.
        """
        request = getattr(self.context, "request", None)
        if not getattr(request, "meta", False):
            return

        try:
            # Memoised: when the label filter has already run - every request kind
            # but a GIF - this hands back the verdict it stored and does no work.
            await decide_for_request(self.context)
        except Exception:  # noqa: BLE001
            # A missing verdict belongs in the payload, not raised at a client.
            logger.exception("[AiLabel] could not evaluate provenance for /meta/")

    def _load_results(self, context):
        results, content_type = super()._load_results(context)
        if getattr(context.request, "meta", False):
            results = meta.inject(context, results)
        return results, content_type
