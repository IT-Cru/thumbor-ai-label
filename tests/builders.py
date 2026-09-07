"""Synthetic container builders.

Hand-built byte streams let a test target one structural edge case exactly - a
gap in extended XMP, an out-of-order JUMBF packet - which is hard to coax out of
a real encoder. Tests against real encoder output live in test_real_images.py.
"""

from __future__ import annotations

import io
import struct
import zlib

from PIL import Image

JPEG_XMP_SIG = b"http://ns.adobe.com/xap/1.0/\x00"
JPEG_XMP_EXT_SIG = b"http://ns.adobe.com/xmp/extension/\x00"
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


# -- JPEG ----------------------------------------------------------------


def app(marker: int, payload: bytes) -> bytes:
    return bytes([0xFF, marker]) + struct.pack(">H", len(payload) + 2) + payload


def app1_xmp(xmp: bytes) -> bytes:
    return app(0xE1, JPEG_XMP_SIG + xmp)


def app1_exif(tiff: bytes) -> bytes:
    return app(0xE1, b"Exif\x00\x00" + tiff)


def app1_xmp_ext(guid: bytes, total: int, offset: int, chunk: bytes) -> bytes:
    assert len(guid) == 32
    return app(
        0xE1,
        JPEG_XMP_EXT_SIG + guid + struct.pack(">I", total) + struct.pack(">I", offset) + chunk,
    )


def app11_jumbf(body: bytes, instance: int = 1, sequence: int = 1, tbox: bytes = b"jumb") -> bytes:
    lbox = struct.pack(">I", len(body) + 8)
    return app(
        0xEB,
        b"JP" + struct.pack(">H", instance) + struct.pack(">I", sequence) + lbox + tbox + body,
    )


def build_jpeg(segments=(), entropy: bytes = b"\x11" * 8, eoi: bool = True) -> bytes:
    out = b"\xff\xd8"
    for segment in segments:
        out += segment
    out += app(0xDA, b"\x00" * 10)  # SOS header
    out += entropy
    if eoi:
        out += b"\xff\xd9"
    return out


# -- PNG -----------------------------------------------------------------


def png_chunk(ctype: bytes, data: bytes) -> bytes:
    return (
        struct.pack(">I", len(data))
        + ctype
        + data
        + struct.pack(">I", zlib.crc32(ctype + data) & 0xFFFFFFFF)
    )


def itxt(keyword: bytes, text: bytes, compressed: bool = False) -> bytes:
    flag = 1 if compressed else 0
    payload = zlib.compress(text) if compressed else text
    return png_chunk(
        b"iTXt",
        keyword + b"\x00" + bytes([flag, 0]) + b"\x00" + b"\x00" + payload,
    )


def raw_profile(kind: bytes, blob: bytes, ctype: bytes = b"tEXt") -> bytes:
    """An ImageMagick-style hex-wrapped profile chunk."""
    hex_body = blob.hex().encode("ascii")
    body = b"\n" + kind + b"\n" + str(len(blob)).encode("ascii") + b"\n" + hex_body
    keyword = b"Raw profile type " + kind
    if ctype == b"zTXt":
        return png_chunk(b"zTXt", keyword + b"\x00" + b"\x00" + zlib.compress(body))
    return png_chunk(b"tEXt", keyword + b"\x00" + body)


def build_png(chunks=(), iend: bool = True) -> bytes:
    out = PNG_MAGIC + png_chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
    for chunk in chunks:
        out += chunk
    out += png_chunk(b"IDAT", zlib.compress(b"\x00\xff\xff\xff"))
    if iend:
        out += png_chunk(b"IEND", b"")
    return out


# -- WebP ----------------------------------------------------------------


def riff_chunk(fourcc: bytes, data: bytes) -> bytes:
    out = fourcc + struct.pack("<I", len(data)) + data
    if len(data) & 1:
        out += b"\x00"
    return out


def build_webp(chunks=()) -> bytes:
    body = b"WEBP" + riff_chunk(b"VP8 ", b"\x22" * 10)
    for chunk in chunks:
        body += chunk
    return b"RIFF" + struct.pack("<I", len(body)) + body


# -- GIF -----------------------------------------------------------------

CV = "http://cv.iptc.org/newscodes/digitalsourcetype/"
NS = 'xmlns:Iptc4xmpExt="http://iptc.org/std/Iptc4xmpExt/2008-02-29/"'

#: XMP's GIF serialisation (XMP spec part 3): the Extension Introducer and
#: Application Extension Label, a block size of 11, then the 8-byte application
#: identifier "XMP Data" and the 3-byte auth code "XMP".
XMP_APP_LABEL = b"\x21\xff\x0bXMP DataXMP"

#: The magic trailer that follows the packet: 0x01, then 0xFF down to 0x00, then the
#: Block Terminator - 258 bytes, matching MAGIC_TRAILER_LEN in Adobe's XMP Toolkit.
#:
#: The packet itself is written raw rather than chunked into sub-blocks, so this is
#: what keeps a GIF reader that knows nothing about XMP from getting lost: walking
#: length-prefixed sub-blocks through the packet always overshoots into the
#: descending run, where each byte's value is exactly the distance left to the
#: terminator, so any landing point funnels to the single 0x00 at the end. The
#: leading 0x01 covers the one jump that jumps to the trailer's first byte, bouncing
#: it back into the run.
#:
#: Written out properly because #25 will read this file as its reference for the
#: format - a fixture that is merely close enough to pass would send that walker
#: after the wrong bytes.
XMP_MAGIC_TRAILER = b"\x01" + bytes(range(255, -1, -1)) + b"\x00"
GIF_TRAILER = b"\x3b"


def gif(term: str | None = None, frames: int = 1, size=(240, 180)) -> bytes:
    """A GIF89a, optionally carrying a DigitalSourceType assertion in XMP.

    Each frame is one flat colour, and ``dither=NONE`` is what keeps it that way:
    the default palette conversion dithers even a uniform fill into a mix of eight
    web-palette colours. A test asking "was anything drawn here" needs a background
    that is genuinely uniform, or every corner looks drawn on.
    """
    images = [
        Image.new("RGB", size, (40 + 50 * index, 110, 160)).convert("P", dither=Image.Dither.NONE)
        for index in range(frames)
    ]
    buf = io.BytesIO()
    images[0].save(buf, "GIF", save_all=True, append_images=images[1:], duration=120, loop=0)
    raw = buf.getvalue()

    if term is None:
        return raw

    xmp = (
        '<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF><rdf:Description '
        f'{NS} Iptc4xmpExt:DigitalSourceType="{CV}{term}"/></rdf:RDF></x:xmpmeta>'
    ).encode()
    assert raw.endswith(GIF_TRAILER)
    return raw[: -len(GIF_TRAILER)] + XMP_APP_LABEL + xmp + XMP_MAGIC_TRAILER + GIF_TRAILER


def gif_sub_blocks(data: bytes) -> bytes:
    """Chunk ``data`` into GIF sub-blocks and terminate the chain.

    Joined rather than accumulated with ``+=``: a sub-block holds at most 255 bytes,
    so a multi-megabyte payload is hundreds of thousands of pieces and repeated
    concatenation turns the builder quadratic. The performance test builds 32 MB
    this way, and that alone cost 45 seconds before this was a join.
    """
    pieces = []
    for offset in range(0, len(data), 255):
        piece = data[offset : offset + 255]
        pieces.append(bytes([len(piece)]))
        pieces.append(piece)
    pieces.append(b"\x00")
    return b"".join(pieces)


def gif_colour_table_len(packed: int) -> int:
    return 3 * (2 << (packed & 0x07)) if packed & 0x80 else 0


def gif_extension(label: int, payload: bytes) -> bytes:
    """A non-application extension - graphic control, comment, plain text."""
    return b"\x21" + bytes([label]) + gif_sub_blocks(payload)


def gif_app_extension(identifier: bytes, body: bytes) -> bytes:
    """An Application Extension. ``body`` is written after the identifier verbatim.

    Verbatim because XMP's serialisation is *not* a sub-block chain - pass
    ``gif_sub_blocks(...)`` explicitly for the extensions that are.
    """
    return b"\x21\xff" + bytes([len(identifier)]) + identifier + body


def gif_xmp_extension(xmp: bytes, magic_trailer: bool = True) -> bytes:
    """XMP as the spec stores it: the packet raw, then the magic trailer."""
    body = xmp + XMP_MAGIC_TRAILER if magic_trailer else gif_sub_blocks(xmp)
    return gif_app_extension(b"XMP DataXMP", body)


def gif_image_block(packed: int = 0x00, data: bytes = b"\x00") -> bytes:
    """A Table Based Image: descriptor, optional local table, code size, data."""
    return (
        b"\x2c"
        + struct.pack("<HHHH", 0, 0, 4, 4)
        + bytes([packed])
        + b"\x00" * gif_colour_table_len(packed)
        + b"\x08"
        + gif_sub_blocks(data)
    )


def build_gif(
    blocks=(), version: bytes = b"89a", packed: int = 0x80, trailer: bool = True
) -> bytes:
    """A hand-built GIF, for the structural edge cases PIL will not produce."""
    out = b"GIF" + version
    out += struct.pack("<HH", 4, 4) + bytes([packed, 0, 0])
    out += b"\x00" * gif_colour_table_len(packed)
    for block in blocks:
        out += block
    return out + GIF_TRAILER if trailer else out
