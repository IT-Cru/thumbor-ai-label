from __future__ import annotations

import struct
import zlib

from thumbor_ai_label.scan import Container, ScanLimits, scan

from .builders import PNG_MAGIC, build_png, itxt, png_chunk, raw_profile

XMP = b'<x:xmpmeta xmlns:x="adobe:ns:meta/"/>'
TIFF = b"MM\x00*\x00\x00\x00\x08" + b"\x00" * 8


def test_recognises_container():
    assert scan(build_png()).container is Container.PNG


def test_bare_png_has_no_metadata():
    result = scan(build_png())
    assert result.has_any_metadata is False
    assert result.truncated is False


def test_extracts_xmp_from_itxt():
    result = scan(build_png([itxt(b"XML:com.adobe.xmp", XMP)]))
    assert result.xmp == [XMP]
    assert result.segments[0].origin == "png:iTXt"


def test_extracts_compressed_xmp_from_itxt():
    assert scan(build_png([itxt(b"XML:com.adobe.xmp", XMP, compressed=True)])).xmp == [XMP]


def test_ignores_itxt_with_an_unrelated_keyword():
    assert scan(build_png([itxt(b"Description", b"a caption")])).xmp == []


def test_extracts_exif_chunk():
    assert scan(build_png([png_chunk(b"eXIf", TIFF)])).exif == [TIFF]


def test_extracts_c2pa_chunk():
    assert scan(build_png([png_chunk(b"caBX", b"jumbf-bytes")])).jumbf == [b"jumbf-bytes"]


def test_metadata_after_the_image_data_is_still_found():
    """PNG legally allows text chunks after IDAT, so the walk must not stop there."""
    raw = build_png()
    tail = itxt(b"XML:com.adobe.xmp", XMP)
    end = raw.rindex(png_chunk(b"IEND", b""))
    assert scan(raw[:end] + tail + raw[end:]).xmp == [XMP]


def test_idat_payload_is_never_materialised():
    big = png_chunk(b"IDAT", zlib.compress(b"\x00" * 5_000_000))
    raw = build_png([itxt(b"XML:com.adobe.xmp", XMP), big])
    result = scan(raw)
    assert result.xmp == [XMP]
    assert result.truncated is False


class TestRawProfiles:
    def test_hex_wrapped_xmp_in_text(self):
        assert scan(build_png([raw_profile(b"xmp", XMP)])).xmp == [XMP]

    def test_hex_wrapped_xmp_in_ztext(self):
        assert scan(build_png([raw_profile(b"xmp", XMP, ctype=b"zTXt")])).xmp == [XMP]

    def test_hex_wrapped_exif_loses_its_framing(self):
        chunk = raw_profile(b"exif", b"Exif\x00\x00" + TIFF)
        assert scan(build_png([chunk])).exif == [TIFF]

    def test_unknown_profile_kind_is_skipped(self):
        assert scan(build_png([raw_profile(b"icc", b"\x00" * 8)])).segments == []

    def test_invalid_hex_is_reported_not_raised(self):
        body = b"\nxmp\n4\nnot-hex-at-all"
        chunk = png_chunk(b"tEXt", b"Raw profile type xmp\x00" + body)
        result = scan(build_png([chunk]))
        assert result.xmp == []
        assert result.truncated is True


class TestMalformed:
    def test_chunk_running_past_the_buffer(self):
        raw = PNG_MAGIC + struct.pack(">I", 9000) + b"iTXt" + b"short"
        result = scan(raw)
        assert result.truncated is True
        assert result.container is Container.PNG

    def test_missing_iend_is_reported(self):
        result = scan(build_png([itxt(b"XML:com.adobe.xmp", XMP)], iend=False))
        assert result.xmp == [XMP]
        assert result.truncated is True

    def test_malformed_itxt_header(self):
        result = scan(build_png([png_chunk(b"iTXt", b"no-null-terminator")]))
        assert result.truncated is True

    def test_itxt_with_unknown_compression_method(self):
        payload = b"XML:com.adobe.xmp\x00" + bytes([1, 7]) + b"\x00\x00" + b"junk"
        result = scan(build_png([png_chunk(b"iTXt", payload)]))
        assert result.xmp == []
        assert result.truncated is True

    def test_bad_crc_does_not_discard_the_payload(self):
        """A wrong CRC does not change what an assertion says; other tools read it too."""
        good = itxt(b"XML:com.adobe.xmp", XMP)
        broken = good[:-4] + b"\xde\xad\xbe\xef"
        assert scan(build_png([broken])).xmp == [XMP]


def test_decompression_bomb_is_capped():
    bomb = itxt(b"XML:com.adobe.xmp", b"A" * 4_000_000, compressed=True)
    result = scan(build_png([bomb]), ScanLimits(max_xmp_bytes=4096))
    assert result.truncated is True
    assert all(len(x) <= 4096 for x in result.xmp)


class TestTextChunkEdges:
    def test_raw_profile_carried_in_itxt(self):
        hex_body = b"\nxmp\n" + str(len(XMP)).encode() + b"\n" + XMP.hex().encode()
        chunk = itxt(b"Raw profile type xmp", hex_body)
        assert scan(build_png([chunk])).xmp == [XMP]

    def test_text_chunk_without_a_null_separator(self):
        result = scan(build_png([png_chunk(b"tEXt", b"no-separator-here")]))
        assert result.truncated is True

    def test_ordinary_text_chunk_is_skipped(self):
        assert scan(build_png([png_chunk(b"tEXt", b"Comment\x00hello")])).segments == []

    def test_empty_ztext_body(self):
        chunk = png_chunk(b"zTXt", b"Raw profile type xmp\x00")
        result = scan(build_png([chunk]))
        assert result.segments == []

    def test_raw_profile_missing_its_header_lines(self):
        chunk = png_chunk(b"tEXt", b"Raw profile type xmp\x00\nxmp\n")
        result = scan(build_png([chunk]))
        assert result.xmp == []
        assert result.truncated is True
