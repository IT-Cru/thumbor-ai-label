"""AI provenance detectors.

Each detector reads one class of signal out of a scanned buffer and returns a
Detection, or None if it has nothing to say. Detectors are selected and ordered by
config and resolved through an entry point group, so a deployment can add its own.
"""

from .registry import (
    BUILTIN_DETECTORS,
    DEFAULT_DETECTORS,
    ENTRY_POINT_GROUP,
    Detector,
    DetectorConfigurationError,
    best_detection,
    load_detectors,
    run_detectors,
)
from .types import (
    IPTC_SOURCE_TYPES,
    Confidence,
    Detection,
    SourceType,
    resolve_iptc_term,
)

__all__ = [
    "Confidence",
    "Detection",
    "SourceType",
    "Detector",
    "DetectorConfigurationError",
    "load_detectors",
    "run_detectors",
    "best_detection",
    "resolve_iptc_term",
    "IPTC_SOURCE_TYPES",
    "BUILTIN_DETECTORS",
    "DEFAULT_DETECTORS",
    "ENTRY_POINT_GROUP",
]
