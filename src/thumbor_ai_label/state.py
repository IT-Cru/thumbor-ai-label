"""Per-request state shared between the engine hook and the filter.

Thumbor builds a fresh Context for every request (``ContextHandler.initialize``),
and the engine is constructed per context, so attributes parked here cannot leak
one image's verdict onto another.

The scan result is stored rather than the buffer: it holds only the extracted
metadata slices, typically a few KB, so nothing keeps a decoded original alive
for the length of the request.
"""

from __future__ import annotations

from .policy import Decision
from .scan import ScanResult

SCAN_ATTR = "_ai_label_scan"
DECISION_ATTR = "_ai_label_decision"

#: Set on the *engine*, not the context. The always-on handler and an explicit
#: ai_label() in the URL can both register the filter, and the label must be pasted
#: once. Marking the engine rather than the request keeps animated images correct:
#: each frame has its own engine, so each frame is still labelled exactly once.
DRAWN_ATTR = "_ai_label_drawn"


def store_scan(context, result: ScanResult) -> None:
    setattr(context, SCAN_ATTR, result)


def get_scan(context) -> ScanResult | None:
    return getattr(context, SCAN_ATTR, None)


def store_decision(context, decision: Decision) -> None:
    setattr(context, DECISION_ATTR, decision)


def get_decision(context) -> Decision | None:
    return getattr(context, DECISION_ATTR, None)


def mark_drawn(engine) -> None:
    setattr(engine, DRAWN_ATTR, True)


def already_drawn(engine) -> bool:
    return bool(getattr(engine, DRAWN_ATTR, False))
