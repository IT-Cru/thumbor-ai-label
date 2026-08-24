from __future__ import annotations

import struct

from thumbor_ai_label.scan import Container, scan

from .builders import build_webp, riff_chunk

XMP = b'<x:xmpmeta xmlns:x="adobe:ns:meta/"/>'
TIFF = b"II*\x00\x08\x00\x00\x00" + b"\x00" * 8


def test_recognises_container():
    assert scan(build_webp()).container is Container.WEBP


def test_bare_webp_has_no_metadata():
    result = scan(build_webp())
    assert result.has_any_metadata is False
    assert result.truncated is False


def test_extracts_xmp():
    result = scan(build_webp([riff_chunk(b"XMP ", XMP)]))
    assert result.xmp == [XMP]
    assert result.segments[0].origin == "webp:XMP"


def test_extracts_raw_tiff_exif():
    assert scan(build_webp([riff_chunk(b"EXIF", TIFF)])).exif == [TIFF]


def test_strips_jpeg_style_exif_framing_when_an_encoder_adds_it():
    chunk = riff_chunk(b"EXIF", b"Exif\x00\x00" + TIFF)
    assert scan(build_webp([chunk])).exif == [TIFF]


def test_extracts_c2pa_chunk():
    assert scan(build_webp([riff_chunk(b"C2PA", b"jumbf-bytes")])).jumbf == [b"jumbf-bytes"]


def test_odd_sized_chunk_padding_is_honoured():
    """A missed pad byte would desync every following chunk."""
    raw = build_webp([riff_chunk(b"ICCP", b"odd"), riff_chunk(b"XMP ", XMP)])
    assert scan(raw).xmp == [XMP]


def test_data_appended_after_the_declared_riff_size_is_not_walked():
    raw = build_webp([riff_chunk(b"XMP ", XMP)]) + riff_chunk(b"XMP ", b"<appended/>")
    assert scan(raw).xmp == [XMP]


class TestMalformed:
    def test_riff_that_is_not_webp(self):
        raw = b"RIFF" + struct.pack("<I", 4) + b"WAVE"
        result = scan(raw)
        assert result.container is None  # sniffed as unrecognised, never dispatched

    def test_chunk_running_past_the_buffer(self):
        body = b"WEBP" + b"XMP " + struct.pack("<I", 9000) + b"short"
        raw = b"RIFF" + struct.pack("<I", len(body)) + body
        result = scan(raw)
        assert result.truncated is True
        assert any("past end" in note for note in result.notes)

    def test_understated_riff_size_does_not_underflow(self):
        body = b"WEBP" + riff_chunk(b"XMP ", XMP)
        raw = b"RIFF" + struct.pack("<I", 0) + body
        result = scan(raw)
        assert result.container is Container.WEBP
        assert result.truncated is False
