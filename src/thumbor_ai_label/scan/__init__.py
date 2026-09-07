"""Container metadata scanner.

Lifts XMP, EXIF and JUMBF payloads out of JPEG, PNG, WebP and GIF buffers without
decoding pixels. GIF carries XMP only - there is no interoperable place for EXIF
in one. Deliberately free of any Thumbor import so it can be tested and
reused independently.
"""

from .scanner import scan, sniff
from .types import (
    DEFAULT_LIMITS,
    Container,
    RawSegment,
    ScanLimits,
    ScanResult,
    SegmentKind,
)

__all__ = [
    "DEFAULT_LIMITS",
    "Container",
    "RawSegment",
    "ScanLimits",
    "ScanResult",
    "SegmentKind",
    "scan",
    "sniff",
]
