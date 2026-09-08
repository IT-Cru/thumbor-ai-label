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


class TestBudgetsAreCheckedBeforeCopying:
    """A payload too big to keep must not be materialised in order to find that out.

    PNG is where this mattered most: a text chunk's header used to be located by
    copying the whole chunk, and a raw profile was expanded through a body slice, a
    split, a joined hex string and an ASCII decode - roughly four times the buffer -
    before the budget was consulted. Both are now measured in place.
    """

    def test_an_oversized_raw_profile_is_refused_without_decoding(self):
        big = b"<x:xmpmeta>" + b"y" * 20_000 + b"</x:xmpmeta>"
        result = scan(build_png([raw_profile(b"xmp", big)]), ScanLimits(max_xmp_bytes=1000))

        assert result.xmp == []
        assert result.truncated is True
        assert any("byte budget exhausted" in note for note in result.notes)

    def test_an_oversized_itxt_is_refused(self):
        big = b"<x:xmpmeta>" + b"y" * 20_000 + b"</x:xmpmeta>"
        chunk = itxt(b"XML:com.adobe.xmp", big)
        result = scan(build_png([chunk]), ScanLimits(max_xmp_bytes=1000))

        assert result.xmp == []
        assert any("byte budget exhausted" in note for note in result.notes)

    def test_a_profile_padded_with_whitespace_costs_its_real_size(self):
        """ImageMagick wraps hex across lines, so stored size overstates the payload.

        Measuring the stored bytes rather than the hex digits would refuse a profile
        that fits, and would do it more often the more the writer wrapped.
        """
        payload = b"<x:xmpmeta>" + b"z" * 400 + b"</x:xmpmeta>"
        hex_text = payload.hex().encode("ascii")
        wrapped = b"\n".join(hex_text[i : i + 78] for i in range(0, len(hex_text), 78))
        body = b"\nxmp\n" + str(len(payload)).encode() + b"\n" + wrapped
        chunk = png_chunk(b"tEXt", b"Raw profile type xmp\x00" + body)

        # A budget that fits the payload but not the wrapped hex it arrived in.
        result = scan(build_png([chunk]), ScanLimits(max_xmp_bytes=len(payload)))
        assert result.xmp == [payload]

    def test_a_header_field_spanning_the_search_window_is_still_found(self):
        """The windowed search must not miss a delimiter past its first window.

        The translated keyword is the field that can legitimately run long - unlike
        the keyword itself, which the spec caps at 79 bytes.
        """
        from thumbor_ai_label.scan.png import _WINDOW

        translated = b"t" * (_WINDOW * 2 + 13)
        chunk = png_chunk(
            b"iTXt",
            b"XML:com.adobe.xmp\x00" + bytes([0, 0]) + b"\x00" + translated + b"\x00" + XMP,
        )
        result = scan(build_png([chunk]))

        assert result.xmp == [XMP], "the payload after a multi-window field is still read"
        assert result.truncated is False

    def test_a_keyword_longer_than_the_spec_allows_is_malformed(self):
        """79 bytes is the cap (PNG 11.3.4.2), so a NUL further in means damage.

        Bounding the search is what stops a chunk with no NUL at all from being
        copied whole just to discover it has no keyword worth reading.
        """
        from thumbor_ai_label.scan.png import _MAX_KEYWORD

        chunk = png_chunk(b"tEXt", b"k" * (_MAX_KEYWORD + 1) + b"\x00value")
        result = scan(build_png([chunk]))

        assert result.segments == []
        assert result.truncated is True
        assert any("malformed" in note for note in result.notes)

    def test_a_keyword_at_the_maximum_length_is_still_read(self):
        """The bound is the spec's, so it must not reject what the spec allows."""
        from thumbor_ai_label.scan.png import _MAX_KEYWORD

        keyword = b"Raw profile type xmp".ljust(_MAX_KEYWORD, b"x")
        assert len(keyword) == _MAX_KEYWORD
        chunk = png_chunk(b"tEXt", keyword + b"\x00ignored")
        result = scan(build_png([chunk]))

        assert result.truncated is False, "a legal keyword is not damage"

    def test_a_far_off_keyword_delimiter_is_not_copied_up_to(self):
        """A NUL that *is* present, just megabytes in - the case the bound exists for.

        Distinct from a chunk with no NUL at all, which exits on the failed search
        without copying anything. Here the search would have succeeded, and the
        keyword slice was the allocation: 8 MB of it, to learn the keyword is not one
        this walker reads.
        """
        import tracemalloc

        size = 8 * 1024 * 1024
        chunk = png_chunk(b"iTXt", b"k" * size + b"\x00" + bytes([0, 0]) + b"\x00\x00text")
        raw = build_png([chunk])  # built before the measurement, not inside it

        tracemalloc.start()
        result = scan(raw)
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        assert result.segments == []
        assert peak < 1024 * 1024, (
            f"peaked at {peak / 1024 / 1024:.1f} MB reading a keyword out of an "
            f"{size / 1024 / 1024:.0f} MB chunk"
        )

    def test_peak_allocation_does_not_track_the_buffer(self):
        """The property the whole change exists for, asserted rather than described.

        A 24 MB profile against a 2 MB budget used to peak near 100 MB. The bound
        here is deliberately loose - it is catching a return to copy-then-check, not
        policing a byte count.
        """
        import tracemalloc

        big = b"<x:xmpmeta>" + b"y" * (12 * 1024 * 1024) + b"</x:xmpmeta>"
        raw = build_png([raw_profile(b"xmp", big)])

        tracemalloc.start()
        result = scan(raw, ScanLimits(max_xmp_bytes=1024))
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        assert result.xmp == [], "far too big to keep"
        assert peak < 4 * 1024 * 1024, (
            f"peaked at {peak / 1024 / 1024:.1f} MB on a {len(raw) / 1024 / 1024:.0f} MB "
            "buffer; a payload is being copied before the budget refuses it"
        )
