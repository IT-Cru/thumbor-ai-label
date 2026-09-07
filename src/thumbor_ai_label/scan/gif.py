"""GIF block walker.

GIF is a chain of blocks rather than length-prefixed chunks, so the walk has to
step over image data by decoding its structure - a Table Based Image is a colour
table, an LZW code size and a run of sub-blocks, none of which is inflated here.
Cost stays proportional to the number of blocks, as it is for PNG and WebP.

Only XMP is lifted. GIF89a carries it as an Application Extension labelled
``XMP DataXMP`` (XMP Specification Part 3), which is where a ``DigitalSourceType``
assertion lives. There is no interoperable place for EXIF in a GIF, and Comment
Extensions are free text with no agreed structure, so neither is collected: a
detector needs a payload it can parse, not any bytes at all.

**The XMP packet is not written as sub-blocks.** It is stored raw and followed by a
258-byte magic trailer whose descending bytes let a reader that knows nothing about
XMP walk the packet as though it were a sub-block chain and still land on the
terminator. That makes the extraction unusual: walk the chain to find where the
block ends, then subtract the trailer to find where the packet ends.
"""

from __future__ import annotations

from .types import ScanLimits, ScanResult, SegmentKind

MAGIC = b"GIF8"

#: 87a predates Application Extensions, so XMP in one is already non-conformant.
#: The block structure is identical, so it is walked anyway and simply finds
#: nothing in a well-formed file.
VERSIONS = (b"87a", b"89a")

HEADER_LEN = 6
SCREEN_DESCRIPTOR_LEN = 7
IMAGE_DESCRIPTOR_LEN = 10

EXTENSION_INTRODUCER = 0x21
IMAGE_SEPARATOR = 0x2C
TRAILER = 0x3B

APPLICATION_EXTENSION = 0xFF
APP_ID_LEN = 11
XMP_APP_ID = b"XMP DataXMP"

#: 0x01, then 0xFF down to 0x00, then the Block Terminator. 258 bytes, matching
#: MAGIC_TRAILER_LEN in Adobe's XMP Toolkit, which is what writes and reads it.
#:
#: Each byte of the descending run is the distance left to the terminator, so a
#: reader walking sub-blocks through the raw packet overshoots into the run and is
#: funnelled to the end whatever byte it lands on. That is what lets the packet be
#: stored unchunked without derailing a GIF reader that has never heard of XMP.
MAGIC_TRAILER = b"\x01" + bytes(range(255, -1, -1)) + b"\x00"
MAGIC_TRAILER_LEN = len(MAGIC_TRAILER)


def _colour_table_len(packed: int) -> int:
    """Bytes occupied by the colour table a packed field declares, if any."""
    if not packed & 0x80:
        return 0
    return 3 * (2 << (packed & 0x07))


def _end_of_sub_blocks(view: memoryview, i: int, n: int) -> int | None:
    """Index of the Block Terminator ending the chain at ``i``, or None if it runs off.

    Each sub-block is a length byte followed by that many bytes; a zero length ends
    the chain. Every step advances by at least one, so the walk cannot spin.
    """
    while i < n:
        size = view[i]
        if size == 0:
            return i
        i += 1 + size
    return None


def _read_application_extension(
    view: memoryview, i: int, n: int, result: ScanResult, limits: ScanLimits
) -> int | None:
    """Handle one Application Extension. ``i`` points at its block-size byte."""
    if i >= n:
        result.note(f"application extension at offset {i - 2} has no block size")
        return None

    declared = view[i]
    id_start = i + 1
    id_end = id_start + declared
    if id_end > n:
        result.note(f"application extension at offset {i} runs past end of buffer")
        return None

    identifier = bytes(view[id_start:id_end])
    data_start = id_end

    end = _end_of_sub_blocks(view, data_start, n)
    if end is None:
        result.note(f"application extension {identifier!r} is not terminated")
        return None

    # Anything but XMP is stepped over. ICC (ICCRGBG1012) and NETSCAPE looping
    # live here too and say nothing about provenance.
    if declared == APP_ID_LEN and identifier == XMP_APP_ID:
        _collect_xmp(view, data_start, end, result, limits)

    return end + 1


def _join_sub_blocks(view: memoryview, i: int, terminator: int) -> bytes:
    """Concatenate a sub-block chain's payloads, dropping the length prefixes."""
    out = bytearray()
    while i < terminator:
        size = view[i]
        out += view[i + 1 : i + 1 + size]
        i += 1 + size
    return bytes(out)


def _collect_xmp(
    view: memoryview, start: int, terminator: int, result: ScanResult, limits: ScanLimits
) -> None:
    """Lift the XMP packet out of an ``XMP DataXMP`` block's payload.

    ``terminator`` indexes the Block Terminator, so the block spans
    ``[start, terminator]`` inclusive. Which of the two encodings it holds is
    settled by looking for the trailer rather than assuming:

    * **Conformant** - the packet raw, then the magic trailer. Slice it off.
    * **Chunked** - a writer that put the packet through the ordinary sub-block
      machinery. Not what the spec says, but reassembling costs little and the
      alternative is handing a detector the length prefixes as though they were
      part of the XML.
    """
    block_end = terminator + 1
    packet_end = block_end - MAGIC_TRAILER_LEN

    if packet_end > start and bytes(view[packet_end:block_end]) == MAGIC_TRAILER:
        payload = bytes(view[start:packet_end])
    else:
        payload = _join_sub_blocks(view, start, terminator)
        result.note("XMP block carries no magic trailer; read as sub-blocks")

    if payload:
        result.add(SegmentKind.XMP, payload, "gif:XMP DataXMP", limits)


def _skip_extension(
    view: memoryview, i: int, n: int, result: ScanResult, limits: ScanLimits
) -> int | None:
    """``i`` points at the Extension Introducer. Returns the next block's offset."""
    label_at = i + 1
    if label_at >= n:
        result.note(f"extension at offset {i} has no label")
        return None

    label = view[label_at]
    body = label_at + 1

    if label == APPLICATION_EXTENSION:
        return _read_application_extension(view, body, n, result, limits)

    end = _end_of_sub_blocks(view, body, n)
    if end is None:
        result.note(f"extension 0x{label:02x} at offset {i} is not terminated")
        return None
    return end + 1


def _skip_image(view: memoryview, i: int, n: int, result: ScanResult) -> int | None:
    """``i`` points at the Image Separator. Steps over the image without decoding it."""
    if i + IMAGE_DESCRIPTOR_LEN > n:
        result.note(f"image descriptor at offset {i} runs past end of buffer")
        return None

    # The packed field is the descriptor's last byte and declares the local table.
    after_table = i + IMAGE_DESCRIPTOR_LEN + _colour_table_len(view[i + IMAGE_DESCRIPTOR_LEN - 1])
    lzw_code_size = after_table  # one byte, then the compressed sub-blocks
    if lzw_code_size >= n:
        result.note(f"image data at offset {i} runs past end of buffer")
        return None

    end = _end_of_sub_blocks(view, lzw_code_size + 1, n)
    if end is None:
        result.note(f"image data at offset {i} is not terminated")
        return None
    return end + 1


def scan_gif(view: memoryview, result: ScanResult, limits: ScanLimits) -> None:
    n = len(view)
    if n < HEADER_LEN + SCREEN_DESCRIPTOR_LEN:
        result.note("buffer is too short to hold a GIF screen descriptor")
        result.truncated = True
        return

    version = bytes(view[3:HEADER_LEN])
    if version not in VERSIONS:
        # Walked anyway: the block grammar has not changed, and a file claiming an
        # unknown version still parses or still fails on its own terms.
        result.note(f"unknown GIF version {version!r}")

    packed = view[HEADER_LEN + 4]
    i = HEADER_LEN + SCREEN_DESCRIPTOR_LEN + _colour_table_len(packed)

    while i < n:
        marker = view[i]

        if marker == TRAILER:
            return
        if marker == EXTENSION_INTRODUCER:
            nxt = _skip_extension(view, i, n, result, limits)
        elif marker == IMAGE_SEPARATOR:
            nxt = _skip_image(view, i, n, result)
        else:
            result.note(f"unknown block 0x{marker:02x} at offset {i}")
            result.truncated = True
            return

        if nxt is None:
            result.truncated = True
            return
        i = nxt

    result.note("reached end of buffer before the GIF trailer")
    result.truncated = True
