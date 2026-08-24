"""Container metadata scanner.

Lifts XMP, EXIF and JUMBF payloads out of JPEG, PNG and WebP buffers without
decoding pixels. Deliberately free of any Thumbor import so it can be tested and
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
    "scan",
    "sniff",
    "Container",
    "SegmentKind",
    "RawSegment",
    "ScanResult",
    "ScanLimits",
    "DEFAULT_LIMITS",
]
