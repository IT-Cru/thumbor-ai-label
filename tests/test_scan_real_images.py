"""Round-trip tests against a real encoder.

The synthetic builders prove the walkers handle structural edge cases; these prove
the walkers agree with what an encoder actually emits.
"""

from __future__ import annotations

import io

import pytest

from thumbor_ai_label.scan import Container, scan

PIL = pytest.importorskip("PIL", reason="Pillow is only needed for encoder round-trips")

from PIL import Image  # noqa: E402 - imports follow a runtime skip guard
from PIL.PngImagePlugin import PngInfo  # noqa: E402 - imports follow a runtime skip guard

XMP = (
    b'<?xpacket begin="\xef\xbb\xbf" id="W5M0MpCehiHzreSzNTczkc9d"?>'
    b'<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF '
    b'xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"/></x:xmpmeta>'
    b'<?xpacket end="w"?>'
)


@pytest.fixture
def image():
    return Image.new("RGB", (32, 24), (120, 30, 30))


@pytest.fixture
def exif(image):
    data = image.getexif()
    data[0x0131] = "TestSoftware 1.0"  # Software
    return data


def encode(image, fmt, **kwargs):
    buf = io.BytesIO()
    image.save(buf, fmt, **kwargs)
    return buf.getvalue()


@pytest.mark.parametrize("fmt,container", [("JPEG", Container.JPEG), ("WEBP", Container.WEBP)])
def test_xmp_and_exif_round_trip(image, exif, fmt, container):
    result = scan(encode(image, fmt, xmp=XMP, exif=exif))
    assert result.container is container
    assert result.xmp == [XMP]
    assert len(result.exif) == 1
    assert result.exif[0][:2] in (b"II", b"MM")  # a real TIFF header
    assert result.truncated is False


def test_png_xmp_and_exif_round_trip(image, exif):
    # Pillow's `xmp=` kwarg is a no-op for PNG, so real PNG XMP goes through PngInfo.
    info = PngInfo()
    info.add_itxt("XML:com.adobe.xmp", XMP.decode("utf-8"), zip=False)
    result = scan(encode(image, "PNG", pnginfo=info, exif=exif))
    assert result.container is Container.PNG
    assert result.xmp == [XMP]
    assert len(result.exif) == 1
    assert result.truncated is False


def test_png_compressed_xmp_round_trip(image):
    info = PngInfo()
    info.add_itxt("XML:com.adobe.xmp", XMP.decode("utf-8"), zip=True)
    assert scan(encode(image, "PNG", pnginfo=info)).xmp == [XMP]


@pytest.mark.parametrize("fmt", ["JPEG", "PNG", "WEBP"])
def test_clean_image_reports_no_metadata(image, fmt):
    result = scan(encode(image, fmt))
    assert result.has_any_metadata is False
    assert result.truncated is False


def test_progressive_jpeg(image, exif):
    result = scan(encode(image, "JPEG", xmp=XMP, exif=exif, progressive=True))
    assert result.xmp == [XMP]


def test_lossless_webp(image):
    assert scan(encode(image, "WEBP", xmp=XMP, lossless=True)).xmp == [XMP]


def test_xmp_filling_a_whole_segment(image):
    """A payload sitting right against the 64 KB APP1 ceiling.

    Pillow refuses to split oversized XMP across segments, so the multi-segment
    Extended XMP reassembly path is covered synthetically in test_scan_jpeg.py
    instead - there is no encoder here that emits it.
    """
    room = 65533 - len(b"http://ns.adobe.com/xap/1.0/\x00") - len(XMP) - 16
    padding = b"<pad>" + b"x" * room + b"</pad>"
    big = XMP.replace(b"<?xpacket end", padding + b"<?xpacket end")
    result = scan(encode(image, "JPEG", xmp=big))
    assert result.xmp == [big]
    assert result.truncated is False


def test_scan_does_not_decode_pixels(image, exif):
    """A truncated file still yields its metadata - proof no pixel decode happened."""
    raw = encode(image, "JPEG", xmp=XMP, exif=exif)
    half = raw[: len(raw) // 2]
    result = scan(half)
    assert result.xmp == [XMP]
