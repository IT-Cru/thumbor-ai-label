"""Deciding on and drawing the label.

Kept out of the filter module so the logic can be exercised without Thumbor's
filter machinery, and reused by the always-on handler.
"""

from __future__ import annotations

from thumbor.utils import logger

from .compose import apply_label, can_draw_on
from .config import get_settings
from .detect import run_detectors
from .policy import Decision, Reason, decide
from .state import already_drawn, get_decision, get_scan, mark_drawn, store_decision


async def decide_for_request(context) -> Decision:
    """The verdict for this request, computed once and reused.

    Memoised because a filter runs once per frame on an animated image; detection
    should not repeat for every frame of a GIF.
    """
    existing = get_decision(context)
    if existing is not None:
        return existing

    settings = get_settings(context.config)

    if not settings.enabled or not settings.detectors:
        decision = Decision(None, Reason.DETECTION_DISABLED)
        store_decision(context, decision)
        return decision

    scanned = get_scan(context)
    if scanned is None:
        # The engine hook did not run - usually because the configured ENGINE is
        # not wrapped. Say so once, loudly: silently drawing nothing would look
        # like "no AI images here" rather than "detection never ran".
        logger.warning(
            "[AiLabel] no scan result on the request; is ENGINE set to a wrapped engine?"
        )
        decision = Decision(None, Reason.DETECTION_DISABLED)
        store_decision(context, decision)
        return decision

    detections = await run_detectors(scanned, settings.detectors)
    decision = decide(
        scanned,
        detections,
        policy=settings.policy,
        min_confidence=settings.min_confidence,
    )
    store_decision(context, decision)
    return decision


def draw(context, engine, decision: Decision) -> bool:
    """Composite the label for ``decision`` onto ``engine``. Returns whether it drew."""
    if not decision.should_label:
        return False

    settings = get_settings(context.config)

    if not settings.draws(decision.state):
        # Configured out of the visible marking. The verdict still stands and still
        # reaches /meta/, where it reports labelled: false.
        return False

    if already_drawn(engine):
        return False

    if getattr(getattr(context, "request", None), "meta", False):
        # A /meta/ response is JSON. There are no pixels to mark, and the engine at
        # this point is Thumbor's JSONEngine wrapping the real one.
        return False

    if not can_draw_on(engine):
        _warn_cannot_draw(engine)
        return False

    labelled, drawn = apply_label(
        engine.image,
        lambda height: settings.icons.get(decision.state, height),
        settings.layout,
    )
    if drawn:
        engine.image = labelled
        mark_drawn(engine)
    return drawn


#: Engines already warned about, by resolved name. Whether an engine holds a PIL
#: image is a property of the engine type, not of the request, so repeating the
#: warning on every GIF would bury the one line an operator needs under exactly the
#: per-request noise this replaces.
_warned_engines: set[str] = set()


def _engine_name(engine) -> str:
    """The engine an operator configured, not the subclass built on top of it.

    ``AiLabelServiceApp`` wraps whatever sits in ``ENGINE`` and ``GIF_ENGINE`` in a
    generated subclass, and every one of those is called ``AiLabelEngine`` - naming
    that would identify nothing. Walking past our own classes reaches the real one;
    ``object`` is always in the MRO, so there is always something to name.
    """
    prefix = f"{__package__}."
    foreign = [
        klass
        for klass in type(engine).__mro__
        if klass.__module__ != __package__ and not klass.__module__.startswith(prefix)
    ]
    return f"{foreign[0].__module__}.{foreign[0].__name__}"


def _warn_cannot_draw(engine) -> None:
    """Say once, per engine, that this one cannot carry a visible mark.

    An operator can act on this; the ``AttributeError`` it replaces read as a fault
    in the plugin rather than as an engine that was never able to do the job.
    """
    name = _engine_name(engine)
    if name in _warned_engines:
        return
    _warned_engines.add(name)
    logger.warning(
        "[AiLabel] %s holds no PIL image, so no visible label can be drawn on it; "
        "/meta/ reports labelled: false for these images and the DOM disclosure is "
        "the only one they carry. Thumbor's gifsicle engine is one such engine, so "
        "GIFs go out unmarked while USE_GIFSICLE_ENGINE is on.",
        name,
    )


async def apply(context, engine) -> bool:
    """Decide and draw, containing any failure.

    Labelling must not take image delivery down: a bad icon path would otherwise
    turn every request into a 500. The failure is logged at error level so it is
    visible, and ``AI_LABEL_STRICT_ERRORS`` turns it back into a hard failure for
    deployments that would rather serve nothing than serve an unlabelled image.
    """
    try:
        decision = await decide_for_request(context)
        return draw(context, engine, decision)
    except Exception:
        logger.exception("[AiLabel] failed to apply label")
        if _strict_errors(context):
            raise
        return False


def _strict_errors(context) -> bool:
    """Read the strict-errors flag off raw config, not through resolved Settings.

    Settings resolution is itself a thing that can fail - a bad icon path is the
    obvious case - and reading the flag through it would mean a broken icon config
    silently disabled the very setting meant to make broken config fatal.
    """
    try:
        return bool(context.config.AI_LABEL_STRICT_ERRORS)
    except Exception:  # noqa: BLE001 - unreadable config must not silently force strict mode on
        return False
