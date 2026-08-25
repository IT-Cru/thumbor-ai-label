"""JPEG marker-chain walker.

Walks the marker chain over an in-memory buffer and lifts out the APP segments
that can carry provenance. It never touches entropy-coded data and never decodes
a pixel: the walk stops at the first scan header (SOS), which in a conformant
file sits after all metadata. On a typical JPEG that means reading a few KB
regardless of how large the image is.

Two payload types arrive split across multiple segments and are reassembled here:
Adobe Extended XMP (anything over the ~64 KB APP1 ceiling) and JUMBF boxes in
APP11 (how C2PA is carried).
"""

from __future__ import annotations

from .types import ScanLimits, ScanResult, SegmentKind

SOI = 0xD8
EOI = 0xD9
SOS = 0xDA
APP1 = 0xE1
APP11 = 0xEB

# Markers that carry no length field: TEM and the eight restart markers.
_STANDALONE = frozenset({0x01}) | frozenset(range(0xD0, 0xD8))

EXIF_SIG = b"Exif\x00\x00"
XMP_SIG = b"http://ns.adobe.com/xap/1.0/\x00"
XMP_EXT_SIG = b"http://ns.adobe.com/xmp/extension/\x00"
JUMBF_SIG = b"JP"

MAGIC = b"\xff\xd8\xff"


def _be16(view: memoryview, off: int) -> int:
    return (view[off] << 8) | view[off + 1]


def _be32(view: memoryview, off: int) -> int:
    return (view[off] << 24) | (view[off + 1] << 16) | (view[off + 2] << 8) | view[off + 3]


def scan_jpeg(view: memoryview, result: ScanResult, limits: ScanLimits) -> None:
    n = len(view)
    i = 2  # past SOI

    ext_xmp: dict[bytes, list[tuple[int, bytes]]] = {}
    ext_xmp_total: dict[bytes, int] = {}
    jumbf_parts: dict[int, dict[int, bytes]] = {}
    jumbf_head: dict[int, bytes] = {}

    while i < n:
        if view[i] != 0xFF:
            result.note(f"marker desync at offset {i}")
            result.truncated = True
            break

        # Fill bytes: any number of 0xFF may pad the gap before a marker code.
        while i < n and view[i] == 0xFF:
            i += 1
        if i >= n:
            result.note("truncated in marker padding")
            result.truncated = True
            break

        marker = view[i]
        i += 1

        if marker == 0x00:
            # 0xFF00 is byte stuffing, which is only legal inside entropy data.
            result.note(f"byte stuffing outside scan data at offset {i - 2}")
            result.truncated = True
            break
        if marker in _STANDALONE:
            continue
        if marker == EOI:
            break
        if marker == SOS:
            if limits.scan_past_sos:
                # Walking past SOS means skipping entropy-coded data, which cannot
                # be done by length arithmetic - it has no length field. Doing it
                # properly means scanning byte-by-byte for the next non-stuffed
                # marker, which forfeits the whole performance argument.
                result.note("scan_past_sos is not supported; stopped at first scan header")
            break

        if i + 2 > n:
            result.note(f"truncated in segment length at offset {i}")
            result.truncated = True
            break

        seglen = _be16(view, i)
        if seglen < 2:
            result.note(f"invalid segment length {seglen} at offset {i}")
            result.truncated = True
            break

        end = i + seglen
        if end > n:
            result.note(f"segment at offset {i} runs past end of buffer")
            result.truncated = True
            break

        payload = view[i + 2 : end]
        i = end

        if marker == APP1:
            _handle_app1(payload, result, limits, ext_xmp, ext_xmp_total)
        elif marker == APP11:
            _handle_app11(payload, result, jumbf_parts, jumbf_head)

    _flush_extended_xmp(ext_xmp, ext_xmp_total, result, limits)
    _flush_jumbf(jumbf_parts, jumbf_head, result, limits)


def _handle_app1(
    payload: memoryview,
    result: ScanResult,
    limits: ScanLimits,
    ext_xmp: dict[bytes, list[tuple[int, bytes]]],
    ext_xmp_total: dict[bytes, int],
) -> None:
    if payload[: len(EXIF_SIG)] == EXIF_SIG:
        # Hand over the TIFF header onwards; the Exif\0\0 framing is JPEG's, not
        # part of the EXIF structure a detector wants to parse.
        result.add(SegmentKind.EXIF, bytes(payload[len(EXIF_SIG) :]), "jpeg:APP1/Exif", limits)
        return

    if payload[: len(XMP_SIG)] == XMP_SIG:
        result.add(SegmentKind.XMP, bytes(payload[len(XMP_SIG) :]), "jpeg:APP1/xmp", limits)
        return

    if payload[: len(XMP_EXT_SIG)] == XMP_EXT_SIG:
        head = len(XMP_EXT_SIG)
        # GUID(32 ASCII hex) + total length(4) + offset of this chunk(4)
        if len(payload) < head + 40:
            result.note("extended XMP segment too short to carry its header")
            result.truncated = True
            return
        guid = bytes(payload[head : head + 32])
        total = _be32(payload, head + 32)
        offset = _be32(payload, head + 36)
        chunk = bytes(payload[head + 40 :])

        if total > limits.max_xmp_bytes:
            result.note(
                f"extended XMP declares {total} bytes, over the "
                f"{limits.max_xmp_bytes} budget; skipped"
            )
            result.truncated = True
            return

        ext_xmp.setdefault(guid, []).append((offset, chunk))
        ext_xmp_total[guid] = total


def _handle_app11(
    payload: memoryview,
    result: ScanResult,
    parts: dict[int, dict[int, bytes]],
    heads: dict[int, bytes],
) -> None:
    # CI('JP') + En(2, box instance) + Z(4, packet sequence) + LBox(4) + TBox(4)
    if payload[: len(JUMBF_SIG)] != JUMBF_SIG:
        return
    if len(payload) < 16:
        result.note("APP11 segment too short to carry a JUMBF packet header")
        result.truncated = True
        return

    instance = _be16(payload, 2)
    sequence = _be32(payload, 4)
    box_header = bytes(payload[8:16])  # LBox + TBox, repeated on every packet
    body = bytes(payload[16:])

    bucket = parts.setdefault(instance, {})
    if sequence in bucket:
        result.note(f"duplicate JUMBF packet sequence {sequence} for instance {instance}")
        return
    bucket[sequence] = body
    heads.setdefault(instance, box_header)


def _flush_extended_xmp(
    ext_xmp: dict[bytes, list[tuple[int, bytes]]],
    totals: dict[bytes, int],
    result: ScanResult,
    limits: ScanLimits,
) -> None:
    for guid, chunks in ext_xmp.items():
        chunks.sort(key=lambda pair: pair[0])
        expected = totals.get(guid, 0)

        # Chunks are keyed by byte offset, so a gap means a missing segment. Splicing
        # across one would silently produce corrupt XML, so hand over what is
        # contiguous from the start and say the rest is missing.
        assembled = bytearray()
        for offset, chunk in chunks:
            if offset != len(assembled):
                result.note(
                    "extended XMP {} has a gap at offset {}; kept the first {} bytes".format(
                        guid.decode("ascii", "replace"), offset, len(assembled)
                    )
                )
                result.truncated = True
                break
            assembled += chunk

        if not assembled:
            continue
        if expected and len(assembled) != expected:
            result.note(
                "extended XMP {} assembled {} of {} declared bytes".format(
                    guid.decode("ascii", "replace"), len(assembled), expected
                )
            )
            result.truncated = True
        result.add(SegmentKind.XMP, bytes(assembled), "jpeg:APP1/xmp-extension", limits)


def _flush_jumbf(
    parts: dict[int, dict[int, bytes]],
    heads: dict[int, bytes],
    result: ScanResult,
    limits: ScanLimits,
) -> None:
    for instance in sorted(parts):
        bucket = parts[instance]
        assembled = bytearray(heads.get(instance, b""))
        for sequence in sorted(bucket):
            assembled += bucket[sequence]
        if len(assembled) > 8:  # more than a bare LBox/TBox
            result.add(
                SegmentKind.JUMBF,
                bytes(assembled),
                f"jpeg:APP11/jumbf#{instance}",
                limits,
            )
