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


#: How much of a chunk is materialised at a time when locating or measuring
#: something inside it. Large enough that the loop overhead is irrelevant, small
#: enough that a hostile chunk cannot turn a search into an allocation.
_WINDOW = 1 << 16

#: What ``bytes.split()`` treats as whitespace, which is what ImageMagick wraps its
#: hex payloads with.
_WHITESPACE = b" \t\n\r\v\f"


def _find(view: memoryview, start: int, char: int = 0) -> int:
    """Index of the next ``char`` at or after ``start``, or -1 if there is none.

    A PNG text chunk's header is a run of delimited fields, and finding them used to
    mean ``bytes(chunk)`` - copying a payload in order to discover it was too big to
    keep. Searching a window at a time costs the same walk and a fixed 64 KB.
    """
    position = start
    total = len(view)
    needle = bytes([char])
    while position < total:
        window = bytes(view[position : position + _WINDOW])
        found = window.find(needle)
        if found >= 0:
            return position + found
        position += _WINDOW
    return -1


def _hex_digit_count(view: memoryview) -> int:
    """How many non-whitespace bytes ``view`` holds, without materialising it.

    Two of these make one decoded byte, so this is the exact size of what a raw
    profile would decode to - known before anything is decoded.
    """
    total = 0
    for position in range(0, len(view), _WINDOW):
        window = bytes(view[position : position + _WINDOW])
        total += len(window) - sum(window.count(char) for char in _WHITESPACE)
    return total


def _strip_whitespace(view: memoryview) -> bytes:
    """Join ``view``'s non-whitespace bytes, a window at a time.

    Peak allocation is one window plus the result, so a payload padded out with
    megabytes of newlines costs its real size rather than its stored size.
    """
    pieces = [
        b"".join(bytes(view[position : position + _WINDOW]).split())
        for position in range(0, len(view), _WINDOW)
    ]
    return b"".join(pieces)


def _inflate(data: bytes, cap: int, result: ScanResult, what: str) -> bytes:
    """Bounded zlib inflate. A compression bomb gets cut off, not honoured."""
    try:
        obj = zlib.decompressobj()
        out = obj.decompress(data, cap)
        if obj.unconsumed_tail:
            result.note(f"{what} decompressed past the {cap} byte cap; truncated")
            result.truncated = True
        return out
    except zlib.error as exc:
        result.note(f"{what} failed to decompress: {exc}")
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
            result.note(f"chunk {ctype!r} at offset {i} runs past end of buffer")
            result.truncated = True
            break

        if ctype == b"IEND":
            saw_iend = True
            break
        if ctype == b"IDAT":
            # Never materialised - skipped by arithmetic.
            i = data_end + 4
            continue

        # Slices, not copies: `add` materialises a payload only once the budget has
        # accepted it.
        if ctype == b"eXIf":
            result.add(SegmentKind.EXIF, view[data_start:data_end], "png:eXIf", limits)
        elif ctype == b"caBX":
            result.add(SegmentKind.JUMBF, view[data_start:data_end], "png:caBX", limits)
        elif ctype == b"iTXt":
            _handle_itxt(view[data_start:data_end], result, limits)
        elif ctype in (b"tEXt", b"zTXt"):
            _handle_text(ctype, view[data_start:data_end], result, limits)

        i = data_end + 4

    if not saw_iend and not result.truncated:
        result.note("reached end of buffer without an IEND chunk")
        result.truncated = True


def _handle_itxt(payload: memoryview, result: ScanResult, limits: ScanLimits) -> None:
    """iTXt: keyword\0 flag(1) method(1) language\0 translated\0 text.

    Walked as a view throughout. The text is handed to ``add`` unmaterialised, so a
    chunk carrying more XMP than the budget allows is refused without ever being
    copied - which is the difference between a bounded scan and a 3x one.
    """
    sep = _find(payload, 0)
    if sep < 0 or len(payload) < sep + 3:
        result.note("malformed iTXt chunk")
        result.truncated = True
        return

    keyword = bytes(payload[:sep])
    compressed = payload[sep + 1]
    method = payload[sep + 2]

    cursor = sep + 3
    for _ in range(2):  # language tag, then translated keyword
        cut = _find(payload, cursor)
        if cut < 0:
            result.note("malformed iTXt chunk: unterminated header field")
            result.truncated = True
            return
        cursor = cut + 1

    rest: memoryview | bytes = payload[cursor:]

    if compressed:
        if method != 0:
            result.note(f"iTXt uses unknown compression method {method}")
            result.truncated = True
            return
        # zlib takes the view directly, so the compressed bytes are not copied
        # either; the cap already bounds what comes out.
        rest = _inflate(rest, limits.max_xmp_bytes, result, f"iTXt {keyword!r}")

    if keyword == XMP_KEYWORD:
        result.add(SegmentKind.XMP, rest, "png:iTXt", limits)
    elif keyword.startswith(RAW_PROFILE_PREFIX):
        _handle_raw_profile(keyword, rest, result, limits, "png:iTXt")


def _handle_text(ctype: bytes, payload: memoryview, result: ScanResult, limits: ScanLimits) -> None:
    """tEXt/zTXt: keyword\0 [method(1)] body. Only raw profiles are of interest."""
    sep = _find(payload, 0)
    if sep < 0:
        result.note(f"malformed {ctype!r} chunk")
        result.truncated = True
        return

    keyword = bytes(payload[:sep])
    if not keyword.startswith(RAW_PROFILE_PREFIX):
        return

    body: memoryview | bytes = payload[sep + 1 :]
    if ctype == b"zTXt":
        if not body:
            return
        # zTXt puts a compression-method byte between the keyword and the data.
        body = _inflate(body[1:], limits.max_xmp_bytes, result, f"zTXt {keyword!r}")

    _handle_raw_profile(keyword, body, result, limits, "png:{}".format(ctype.decode("ascii")))


def _handle_raw_profile(
    keyword: bytes, body: memoryview | bytes, result: ScanResult, limits: ScanLimits, origin: str
) -> None:
    """Decode an ImageMagick raw profile: "\\n<name>\\n<length>\\n<hex...>".

    The hex is measured before it is decoded. Getting here used to cost several
    copies of the chunk - the body, its split, the joined hex, its ASCII decode -
    so a profile far too large to keep was expanded to roughly four times the
    buffer before the budget got a say. Now an oversized one costs the walk.
    """
    kind = _RAW_PROFILE_KINDS.get(keyword[len(RAW_PROFILE_PREFIX) :].strip().lower())
    if kind is None:
        return

    view = memoryview(body) if isinstance(body, bytes) else body

    # "\n<name>\n<length>\n" - three newlines, all near the start.
    cursor = 0
    for _ in range(3):
        cut = _find(view, cursor, 0x0A)
        if cut < 0:
            result.note(f"raw profile {keyword!r} has no hex payload")
            result.truncated = True
            return
        cursor = cut + 1

    hex_view = view[cursor:]
    # Two hex digits per byte, whitespace excluded: the exact decoded size, known
    # without decoding. Six bytes of Exif framing may come off afterwards, so this
    # can overstate by six - conservative in the direction that refuses.
    if not result.accepts(kind, _hex_digit_count(hex_view) // 2, f"{origin}/raw-profile", limits):
        return

    try:
        decoded = bytes.fromhex(_strip_whitespace(hex_view).decode("ascii"))
    except (ValueError, UnicodeDecodeError):
        result.note(f"raw profile {keyword!r} is not valid hex")
        result.truncated = True
        return

    if kind is SegmentKind.EXIF and decoded[:6] == b"Exif\x00\x00":
        decoded = decoded[6:]
    result.add(kind, decoded, f"{origin}/raw-profile", limits)
