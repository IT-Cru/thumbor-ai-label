"""What a detector returns, and the vocabulary it maps onto.

Like the scanner, this module has no Thumbor import.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class SourceType(str, Enum):
    """How an image came to exist, as far as its metadata claims.

    ``NOT_AI`` and ``UNKNOWN`` are deliberately distinct. ``NOT_AI`` is a positive
    assertion - something in the file says "a camera took this". ``UNKNOWN`` is the
    absence of any such claim. The fail-closed policy treats them very differently,
    so collapsing them would quietly defeat it.
    """

    AI_GENERATED = "ai_generated"
    AI_MANIPULATED = "ai_manipulated"
    AI_COMPOSITE = "ai_composite"
    NOT_AI = "not_ai"
    UNKNOWN = "unknown"

    @property
    def is_ai(self) -> bool:
        return self in (
            SourceType.AI_GENERATED,
            SourceType.AI_MANIPULATED,
            SourceType.AI_COMPOSITE,
        )


class Confidence(str, Enum):
    """How much weight the evidence carries.

    HIGH is an explicit standardised assertion. MEDIUM is a structural signal whose
    meaning is clear but unverified. LOW is a heuristic that will produce false
    positives and must never be the sole basis for a strong claim.
    """

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"

    @property
    def rank(self) -> int:
        return {"low": 0, "medium": 1, "high": 2}[self.value]


@dataclass(frozen=True)
class Detection:
    """One detector's reading of one image."""

    source_type: SourceType
    confidence: Confidence
    detector: str
    #: The raw value the verdict was drawn from - a CV URI, a Software tag. Surfaced
    #: on the meta endpoint so a decision can be audited rather than just trusted.
    evidence: str = ""
    #: Which tool made the image, when the metadata names one.
    generator: str | None = None

    @property
    def is_conclusive(self) -> bool:
        """A claim strong enough to stop asking other detectors."""
        return self.confidence is Confidence.HIGH and self.source_type is not SourceType.UNKNOWN


# -- IPTC digital source type vocabulary ---------------------------------

IPTC_DIGITAL_SOURCE_TYPE_NS = "http://iptc.org/std/Iptc4xmpExt/2008-02-29/"
IPTC_CV_PREFIX = "http://cv.iptc.org/newscodes/digitalsourcetype/"

#: IPTC controlled-vocabulary terms mapped onto our states.
#:
#: The vocabulary is extended over time, so this map is not exhaustive and is not
#: meant to be. A term that is not listed resolves to UNKNOWN rather than NOT_AI:
#: an unrecognised term must never be read as a clean bill of health. Deployments
#: can extend or override the map through config.
IPTC_SOURCE_TYPES = {
    # Captured from the physical world.
    "digitalcapture": SourceType.NOT_AI,
    "negativefilm": SourceType.NOT_AI,
    "positivefilm": SourceType.NOT_AI,
    "print": SourceType.NOT_AI,
    "minorhumanedits": SourceType.NOT_AI,
    "compositecapture": SourceType.NOT_AI,
    # Made by a human or by non-generative software.
    "digitalart": SourceType.NOT_AI,
    "virtualrecording": SourceType.NOT_AI,
    "softwareimage": SourceType.NOT_AI,
    "algorithmicmedia": SourceType.NOT_AI,
    # Generative AI.
    "trainedalgorithmicmedia": SourceType.AI_GENERATED,
    "compositewithtrainedalgorithmicmedia": SourceType.AI_COMPOSITE,
    "compositesynthetic": SourceType.AI_COMPOSITE,
    "algorithmicallyenhanced": SourceType.AI_MANIPULATED,
    "datadrivenmedia": SourceType.AI_MANIPULATED,
}


def resolve_iptc_term(value: str) -> tuple[SourceType, str]:
    """Map a DigitalSourceType value onto a state.

    Accepts either the full CV URI or a bare term - both appear in the wild.
    Returns the state and the normalised term that produced it.
    """
    term = value.strip()
    if not term:
        return SourceType.UNKNOWN, ""
    if "/" in term:
        term = term.rstrip("/").rsplit("/", 1)[-1]
    return IPTC_SOURCE_TYPES.get(term.lower(), SourceType.UNKNOWN), term
