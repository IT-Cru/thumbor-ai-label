"""Turns detector findings into a decision about which label to draw.

This is where the fail-closed behaviour lives. No Thumbor import.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum

from .detect import Confidence, Detection, SourceType, best_detection
from .scan import ScanResult, SegmentKind

#: Segment kinds that are *able* to carry a provenance assertion. EXIF is absent on
#: purpose: it defines no field that states how an image was made, so an EXIF block
#: says nothing about provenance either way. Treating it as "metadata present" would
#: put an unknown label on essentially every camera photograph ever taken.
PROVENANCE_CAPABLE = frozenset({SegmentKind.XMP, SegmentKind.JUMBF})


class Policy(str, Enum):
    """What to do when nothing asserts how the image was made.

    STRICT labels anything without a positive not-AI assertion. That is the
    strongest compliance posture and it will label most older content, since
    `DigitalSourceType` is a young field and images predating it do not carry one.

    RELAXED labels only when a provenance-capable block exists but says nothing
    conclusive - which is where a stripped or tampered assertion would show up -
    and stays silent on files that never carried provenance at all.
    """

    STRICT = "strict"
    RELAXED = "relaxed"


class Reason(str, Enum):
    """Why the decision came out the way it did. Surfaced for auditing."""

    AI_ASSERTED = "ai_asserted"
    NOT_AI_ASSERTED = "not_ai_asserted"
    INCONCLUSIVE = "inconclusive"
    NO_PROVENANCE_BLOCK = "no_provenance_block"
    BELOW_MIN_CONFIDENCE = "below_min_confidence"
    DETECTION_DISABLED = "detection_disabled"


@dataclass(frozen=True)
class Decision:
    """The label to draw, or None, plus the reasoning that produced it."""

    state: SourceType | None
    reason: Reason
    detection: Detection | None = None

    @property
    def should_label(self) -> bool:
        return self.state is not None

    def as_dict(self) -> dict:
        """Shape used by the meta endpoint."""
        data = {
            "label": self.state.value if self.state else None,
            "reason": self.reason.value,
        }
        if self.detection is not None:
            data["detector"] = self.detection.detector
            data["confidence"] = self.detection.confidence.value
            data["evidence"] = self.detection.evidence
            if self.detection.generator:
                data["generator"] = self.detection.generator
        return data


def decide(
    scanned: ScanResult,
    detections: Sequence[Detection],
    policy: Policy = Policy.STRICT,
    min_confidence: Confidence = Confidence.LOW,
) -> Decision:
    """Choose the label state for one image.

    ``min_confidence`` gates only the *positive AI* claim. A not-AI assertion is
    always honoured at whatever confidence it carries, because discarding it would
    push the image into the unknown bucket and label it - the opposite of what
    raising the bar was meant to achieve.
    """
    best = best_detection(detections)

    if best is not None:
        if best.source_type.is_ai:
            if best.confidence.rank >= min_confidence.rank:
                return Decision(best.source_type, Reason.AI_ASSERTED, best)
            # Too weak to label as AI, and too weak to clear the image either.
            return _inconclusive(scanned, policy, best, Reason.BELOW_MIN_CONFIDENCE)

        if best.source_type is SourceType.NOT_AI:
            return Decision(None, Reason.NOT_AI_ASSERTED, best)

    return _inconclusive(scanned, policy, best, Reason.INCONCLUSIVE)


def _inconclusive(
    scanned: ScanResult,
    policy: Policy,
    detection: Detection | None,
    reason: Reason,
) -> Decision:
    if policy is Policy.STRICT:
        return Decision(SourceType.UNKNOWN, reason, detection)

    if PROVENANCE_CAPABLE & set(scanned.kinds()):
        return Decision(SourceType.UNKNOWN, reason, detection)

    return Decision(None, Reason.NO_PROVENANCE_BLOCK, detection)
