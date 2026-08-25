"""Result and limit types for the container metadata scanner.

Nothing in this package imports Thumbor. The scanner is pure Python so it can be
unit-tested on any interpreter, independent of Thumbor's dependency pins.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import Enum


class Container(str, Enum):
    """Image container the scanner recognised from the file's magic bytes."""

    JPEG = "jpeg"
    PNG = "png"
    WEBP = "webp"


class SegmentKind(str, Enum):
    """Class of metadata payload, independent of which container carried it."""

    XMP = "xmp"
    EXIF = "exif"
    JUMBF = "jumbf"


@dataclass(frozen=True)
class RawSegment:
    """One metadata payload, extracted but not parsed.

    ``data`` is the payload with its container-specific framing already stripped:
    an ``xmp`` segment starts at the ``<?xpacket`` or ``<x:xmpmeta`` text, an
    ``exif`` segment starts at the TIFF header, a ``jumbf`` segment starts at the
    reassembled box. Interpreting those bytes is a detector's job, not the
    scanner's.
    """

    kind: SegmentKind
    data: bytes
    origin: str

    def __repr__(self) -> str:
        # Payloads can carry personal data (GPS, creator, captions). Keep them out
        # of logs and tracebacks; length and provenance are what debugging needs.
        return (
            f"RawSegment(kind={self.kind.value!r}, origin={self.origin!r}, bytes={len(self.data)})"
        )


@dataclass(frozen=True)
class ScanLimits:
    """Bounds applied while walking an untrusted buffer.

    Every limit exists to stop a hostile or corrupt file from turning a scan into
    unbounded work or unbounded memory. Exceeding one is never an error: the scan
    stops collecting, sets ``truncated`` and records a note.
    """

    max_segments: int = 256
    max_xmp_bytes: int = 2 * 1024 * 1024
    max_exif_bytes: int = 1 * 1024 * 1024
    max_jumbf_bytes: int = 8 * 1024 * 1024

    #: JPEG only. Metadata legally precedes the first scan header, and stopping
    #: there means a scan reads a few KB instead of the whole file. Set True only
    #: to chase metadata in non-conformant files.
    scan_past_sos: bool = False

    def budget_for(self, kind: SegmentKind) -> int:
        if kind is SegmentKind.XMP:
            return self.max_xmp_bytes
        if kind is SegmentKind.EXIF:
            return self.max_exif_bytes
        return self.max_jumbf_bytes


DEFAULT_LIMITS = ScanLimits()


@dataclass
class ScanResult:
    """What a scan found, plus how much it could trust the walk.

    The distinction that matters downstream is between *no metadata at all* and
    *metadata that carried no AI assertion*. The first is the normal state of a
    pre-2023 archive; the second is where a stripped or tampered assertion would
    show up. ``has_any_metadata`` is what the fail-closed policy keys off.
    """

    container: Container | None = None
    segments: list[RawSegment] = field(default_factory=list)
    notes: tuple[str, ...] = ()
    truncated: bool = False

    _used: dict[SegmentKind, int] = field(default_factory=dict, repr=False)

    # -- collection ------------------------------------------------------

    def add(self, kind: SegmentKind, data: bytes, origin: str, limits: ScanLimits) -> bool:
        """Record a payload if it fits the limits. Returns False if it was dropped."""
        if len(self.segments) >= limits.max_segments:
            self.note(f"segment-limit reached ({limits.max_segments}); stopped collecting")
            self.truncated = True
            return False

        used = self._used.get(kind, 0)
        budget = limits.budget_for(kind)
        if used + len(data) > budget:
            self.note(
                f"{kind.value} byte budget exhausted ({used} of {budget}); "
                f"dropped {len(data)} from {origin}"
            )
            self.truncated = True
            return False

        self._used[kind] = used + len(data)
        self.segments.append(RawSegment(kind=kind, data=data, origin=origin))
        return True

    def note(self, message: str) -> None:
        """Record a non-fatal observation about the walk."""
        if message not in self.notes:
            self.notes = (*self.notes, message)

    # -- access ----------------------------------------------------------

    def of(self, kind: SegmentKind) -> list[bytes]:
        return [s.data for s in self.segments if s.kind is kind]

    @property
    def xmp(self) -> list[bytes]:
        return self.of(SegmentKind.XMP)

    @property
    def exif(self) -> list[bytes]:
        return self.of(SegmentKind.EXIF)

    @property
    def jumbf(self) -> list[bytes]:
        return self.of(SegmentKind.JUMBF)

    @property
    def has_any_metadata(self) -> bool:
        """True if the file carried any metadata block the scanner understood.

        False means the file is metadata-free, which under the relaxed fail-closed
        mode is treated as 'nothing to say' rather than 'unproven'.
        """
        return bool(self.segments)

    def kinds(self) -> Sequence[SegmentKind]:
        seen = []
        for segment in self.segments:
            if segment.kind not in seen:
                seen.append(segment.kind)
        return tuple(seen)
