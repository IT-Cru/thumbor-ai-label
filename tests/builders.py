"""Synthetic container builders.

Hand-built byte streams let a test target one structural edge case exactly - a
gap in extended XMP, an out-of-order JUMBF packet - which is hard to coax out of
a real encoder. Tests against real encoder output live in test_real_images.py.
"""

from __future__ import annotations

import struct
import zlib

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
