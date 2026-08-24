"""Detector discovery and execution.

Detectors are selected by name in config. Built-ins are registered here; anything
else is resolved from the ``thumbor_ai_label.detectors`` entry point group, so a
deployment can ship its own - a DAM lookup, a house heuristic - by installing a
package alongside this one.

A detector is any module or object exposing ``NAME``, ``REQUIRES`` and ``detect``.
``detect`` may be sync or async: the built-ins are pure CPU work over bytes already
in memory, but a detector that calls out to another system needs to await, and the
runner accommodates both.
"""

from __future__ import annotations

import inspect
import logging
from dataclasses import dataclass
from importlib.metadata import entry_points
from typing import Any, Dict, Iterable, List, Optional, Sequence

from ..scan import ScanResult, SegmentKind
from . import exif as exif_detector
from . import iptc as iptc_detector
from .types import Confidence, Detection, SourceType

logger = logging.getLogger(__name__)

ENTRY_POINT_GROUP = "thumbor_ai_label.detectors"

BUILTIN_DETECTORS = {
    iptc_detector.NAME: iptc_detector,
    exif_detector.NAME: exif_detector,
}

#: Order used when config names none. XMP first because it is the only signal that
#: is both standardised and unambiguous; the EXIF heuristic trails it so it can
#: only ever speak about images the standard has nothing to say about.
DEFAULT_DETECTORS = (iptc_detector.NAME, exif_detector.NAME)


class DetectorConfigurationError(Exception):
    """Raised at startup for an unresolvable detector name.

    Deliberately fatal at boot rather than skipped per request: a deployment that
    believes it is running a detector it is not would fail open silently, which is
    the exact failure mode the fail-closed policy exists to prevent.
    """


@dataclass(frozen=True)
class Detector:
    """Normalised handle on a detector module or object."""

    name: str
    requires: frozenset
    run: Any

    @classmethod
    def adapt(cls, name: str, target: Any) -> "Detector":
        detect = getattr(target, "detect", None)
        if not callable(detect):
            raise DetectorConfigurationError(
                "detector {!r} ({!r}) has no callable detect()".format(name, target)
            )
        requires = getattr(target, "REQUIRES", None)
        if requires is None:
            requires = getattr(target, "requires", frozenset())
        return cls(
            name=getattr(target, "NAME", None) or getattr(target, "name", name),
            requires=frozenset(requires),
            run=detect,
        )


def _discover() -> Dict[str, Any]:
    found: Dict[str, Any] = {}
    try:
        points = entry_points(group=ENTRY_POINT_GROUP)
    except Exception as exc:  # a broken third-party dist must not stop boot
        logger.warning("could not read %s entry points: %s", ENTRY_POINT_GROUP, exc)
        return found

    for point in points:
        try:
            found[point.name] = point.load()
        except Exception as exc:
            logger.warning("detector entry point %r failed to load: %s", point.name, exc)
    return found


def load_detectors(names: Optional[Iterable[str]] = None) -> List[Detector]:
    """Resolve configured names into runnable detectors, in the order given."""
    requested = list(names) if names is not None else list(DEFAULT_DETECTORS)

    available: Dict[str, Any] = dict(BUILTIN_DETECTORS)
    # Discovery runs only if config asks for something not built in, so the common
    # case does not pay for it at startup.
    if any(name not in available for name in requested):
        available.update(_discover())

    detectors = []
    for name in requested:
        target = available.get(name)
        if target is None:
            raise DetectorConfigurationError(
                "unknown detector {!r}; available: {}".format(
                    name, ", ".join(sorted(available)) or "none"
                )
            )
        detectors.append(Detector.adapt(name, target))
    return detectors


async def run_detectors(
    scanned: ScanResult, detectors: Sequence[Detector]
) -> List[Detection]:
    """Run detectors in order, stopping once one speaks conclusively.

    A detector whose required segment kinds are absent is skipped without being
    called - there is no point asking the XMP detector about a file with no XMP.
    """
    present = set(scanned.kinds())
    detections: List[Detection] = []

    for detector in detectors:
        if detector.requires and not (detector.requires & present):
            continue

        try:
            outcome = detector.run(scanned)
            if inspect.isawaitable(outcome):
                outcome = await outcome
        except Exception:
            # One bad detector must not take down the request or suppress the
            # others. Nothing is returned for it, so the policy sees no claim.
            logger.exception("detector %r raised; ignoring its result", detector.name)
            continue

        if outcome is None:
            continue

        detections.append(outcome)
        if outcome.is_conclusive:
            break

    return detections


def best_detection(detections: Sequence[Detection]) -> Optional[Detection]:
    """Pick the detection that should drive the label.

    An AI claim outranks a not-AI claim at equal confidence: a file asserting both
    is self-contradictory, and under a compliance driver the cautious reading wins.
    """
    if not detections:
        return None
    return max(
        detections,
        key=lambda d: (d.confidence.rank, d.source_type.is_ai, d.source_type is not SourceType.UNKNOWN),
    )
