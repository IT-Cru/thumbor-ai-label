"""WebP (RIFF) chunk walker.

RIFF chunks carry an explicit length, so the walk skips VP8/VP8L image data by
arithmetic exactly as the PNG walker skips IDAT.
"""

from __future__ import annotations

from .types import ScanLimits, ScanResult, SegmentKind

MAGIC = b"RIFF"
FORM = b"WEBP"

EXIF_PREFIX = b"Exif\x00\x00"


def _le32(view: memoryview, off: int) -> int:
    return view[off] | (view[off + 1] << 8) | (view[off + 2] << 16) | (view[off + 3] << 24)


def scan_webp(view: memoryview, result: ScanResult, limits: ScanLimits) -> None:
    n = len(view)
    if n < 12 or bytes(view[8:12]) != FORM:
        result.note("RIFF container is not WEBP")
        result.truncated = True
        return

    # Trust the declared RIFF size over the buffer length so appended junk is not
    # walked as if it were chunks.
    declared = _le32(view, 4) + 8
    if 12 <= declared < n:
        n = declared

    i = 12
    while i + 8 <= n:
        fourcc = bytes(view[i : i + 4])
        size = _le32(view, i + 4)
        data_start = i + 8
        data_end = data_start + size

        if data_end > n:
            result.note("chunk {!r} at offset {} runs past end of buffer".format(fourcc, i))
            result.truncated = True
            break

        if fourcc == b"XMP ":
            result.add(SegmentKind.XMP, bytes(view[data_start:data_end]), "webp:XMP", limits)
        elif fourcc == b"EXIF":
            payload = bytes(view[data_start:data_end])
            # The spec says raw TIFF here, but encoders in the wild still prepend
            # the JPEG-style Exif framing.
            if payload[: len(EXIF_PREFIX)] == EXIF_PREFIX:
                payload = payload[len(EXIF_PREFIX) :]
            result.add(SegmentKind.EXIF, payload, "webp:EXIF", limits)
        elif fourcc == b"C2PA":
            result.add(SegmentKind.JUMBF, bytes(view[data_start:data_end]), "webp:C2PA", limits)

        # RIFF pads odd-sized chunks to an even boundary.
        i = data_end + (size & 1)
