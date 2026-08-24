"""PNG chunk walker.

Walks the chunk list without ever reading an IDAT payload - image data is skipped
by length arithmetic alone, so the cost of a scan is proportional to the number of
chunks, not the size of the image. Unlike JPEG, PNG permits text chunks after the
image data, so the walk continues to IEND rather than stopping at the first IDAT.
"""

from __future__ import annotations

import zlib

from .types import ScanLimits, ScanResult, SegmentKind

MAGIC = b"\x89PNG\r\n\x1a\n"

XMP_KEYWORD = b"XML:com.adobe.xmp"

# ImageMagick and friends re-wrap metadata as hex text under these keywords rather
# than in the purpose-built chunks. Common enough in editorial pipelines to matter.
RAW_PROFILE_PREFIX = b"Raw profile type "
_RAW_PROFILE_KINDS = {b"xmp": SegmentKind.XMP, b"exif": SegmentKind.EXIF}


def _be32(view: memoryview, off: int) -> int:
    return (view[off] << 24) | (view[off + 1] << 16) | (view[off + 2] << 8) | view[off + 3]


def _inflate(data: bytes, cap: int, result: ScanResult, what: str) -> bytes:
    """Bounded zlib inflate. A compression bomb gets cut off, not honoured."""
    try:
        obj = zlib.decompressobj()
        out = obj.decompress(data, cap)
        if obj.unconsumed_tail:
            result.note("{} decompressed past the {} byte cap; truncated".format(what, cap))
            result.truncated = True
        return out
    except zlib.error as exc:
        result.note("{} failed to decompress: {}".format(what, exc))
        result.truncated = True
        return b""


def scan_png(view: memoryview, result: ScanResult, limits: ScanLimits) -> None:
    n = len(view)
    i = len(MAGIC)
    saw_iend = False

    while i + 8 <= n:
        length = _be32(view, i)
        ctype = bytes(view[i + 4 : i + 8])
        data_start = i + 8
        data_end = data_start + length

        # +4 for the trailing CRC, which we do not verify: a wrong CRC does not
        # change what a provenance assertion says, and rejecting on it would drop
        # metadata that every other tool reads fine.
        if data_end + 4 > n:
            result.note("chunk {!r} at offset {} runs past end of buffer".format(ctype, i))
            result.truncated = True
            break

        if ctype == b"IEND":
            saw_iend = True
            break
        if ctype == b"IDAT":
            # Never materialised - skipped by arithmetic.
            i = data_end + 4
            continue

        if ctype == b"eXIf":
            result.add(SegmentKind.EXIF, bytes(view[data_start:data_end]), "png:eXIf", limits)
        elif ctype == b"caBX":
            result.add(SegmentKind.JUMBF, bytes(view[data_start:data_end]), "png:caBX", limits)
        elif ctype == b"iTXt":
            _handle_itxt(view[data_start:data_end], result, limits)
        elif ctype in (b"tEXt", b"zTXt"):
            _handle_text(ctype, view[data_start:data_end], result, limits)

        i = data_end + 4

    if not saw_iend and not result.truncated:
        result.note("reached end of buffer without an IEND chunk")
        result.truncated = True


def _handle_itxt(payload: memoryview, result: ScanResult, limits: ScanLimits) -> None:
    raw = bytes(payload)
    # keyword\0 flag(1) method(1) language\0 translated\0 text
    sep = raw.find(b"\x00")
    if sep < 0 or len(raw) < sep + 3:
        result.note("malformed iTXt chunk")
        result.truncated = True
        return
    keyword = raw[:sep]

    compressed = raw[sep + 1]
    method = raw[sep + 2]
    rest = raw[sep + 3 :]

    for _ in range(2):  # language tag, then translated keyword
        cut = rest.find(b"\x00")
        if cut < 0:
            result.note("malformed iTXt chunk: unterminated header field")
            result.truncated = True
            return
        rest = rest[cut + 1 :]

    if compressed:
        if method != 0:
            result.note("iTXt uses unknown compression method {}".format(method))
            result.truncated = True
            return
        rest = _inflate(rest, limits.max_xmp_bytes, result, "iTXt {!r}".format(keyword))

    if keyword == XMP_KEYWORD:
        result.add(SegmentKind.XMP, rest, "png:iTXt", limits)
    elif keyword.startswith(RAW_PROFILE_PREFIX):
        _handle_raw_profile(keyword, rest, result, limits, "png:iTXt")


def _handle_text(
    ctype: bytes, payload: memoryview, result: ScanResult, limits: ScanLimits
) -> None:
    raw = bytes(payload)
    sep = raw.find(b"\x00")
    if sep < 0:
        result.note("malformed {!r} chunk".format(ctype))
        result.truncated = True
        return
    keyword = raw[:sep]
    if not keyword.startswith(RAW_PROFILE_PREFIX):
        return

    body = raw[sep + 1 :]
    if ctype == b"zTXt":
        if not body:
            return
        # zTXt puts a compression-method byte between the keyword and the data.
        body = _inflate(body[1:], limits.max_xmp_bytes, result, "zTXt {!r}".format(keyword))

    _handle_raw_profile(keyword, body, result, limits, "png:{}".format(ctype.decode("ascii")))


def _handle_raw_profile(
    keyword: bytes, body: bytes, result: ScanResult, limits: ScanLimits, origin: str
) -> None:
    """Decode an ImageMagick raw profile: "\\n<name>\\n<length>\\n<hex...>"."""
    kind = _RAW_PROFILE_KINDS.get(keyword[len(RAW_PROFILE_PREFIX) :].strip().lower())
    if kind is None:
        return

    lines = body.split(b"\n", 3)
    if len(lines) < 4:
        result.note("raw profile {!r} has no hex payload".format(keyword))
        result.truncated = True
        return

    hex_text = b"".join(lines[3].split())
    try:
        decoded = bytes.fromhex(hex_text.decode("ascii"))
    except (ValueError, UnicodeDecodeError):
        result.note("raw profile {!r} is not valid hex".format(keyword))
        result.truncated = True
        return

    if kind is SegmentKind.EXIF and decoded[:6] == b"Exif\x00\x00":
        decoded = decoded[6:]
    result.add(kind, decoded, "{}/raw-profile".format(origin), limits)
