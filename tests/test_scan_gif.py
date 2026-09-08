"""The GIF block walker.

GIF is a chain of blocks rather than length-prefixed chunks, so the walk has to
understand each block well enough to step over it. That makes the malformed cases
the interesting ones: a misread colour table or sub-block chain desyncs everything
after it, and the walk must stop and say so rather than read rubbish as metadata.

`build_gif` and friends produce the structural cases by hand; `gif` produces a real
one through PIL.
"""

from __future__ import annotations

from thumbor_ai_label.scan import Container, ScanLimits, scan
from thumbor_ai_label.scan.gif import MAGIC_TRAILER

from .builders import (
    build_gif,
    gif,
    gif_app_extension,
    gif_extension,
    gif_image_block,
    gif_sub_blocks,
    gif_xmp_extension,
)

XMP = b'<x:xmpmeta xmlns:x="adobe:ns:meta/"/>'


def test_recognises_the_container():
    assert scan(build_gif()).container is Container.GIF


def test_a_bare_gif_has_no_metadata():
    result = scan(build_gif([gif_image_block()]))
    assert result.has_any_metadata is False
    assert result.truncated is False
    assert result.notes == ()


def test_extracts_xmp():
    result = scan(build_gif([gif_xmp_extension(XMP)]))
    assert result.xmp == [XMP]
    assert result.segments[0].origin == "gif:XMP DataXMP"


def test_the_magic_trailer_is_not_part_of_the_packet():
    """258 bytes of trailer handed to a detector would be 258 bytes of noise."""
    result = scan(build_gif([gif_xmp_extension(XMP)]))
    assert MAGIC_TRAILER not in result.xmp[0]
    assert result.xmp[0].endswith(b"/>")


def test_a_real_gif_from_an_encoder_is_walked():
    result = scan(gif(term="trainedAlgorithmicMedia"))
    assert result.notes == (), "a clean walk to the trailer"
    assert b"trainedAlgorithmicMedia" in result.xmp[0]


def test_an_animation_is_stepped_over_to_reach_the_metadata():
    result = scan(gif(term="trainedAlgorithmicMedia", frames=4))
    assert result.notes == ()
    assert len(result.xmp) == 1


def test_metadata_after_the_image_is_still_found():
    """Unlike JPEG, there is no scan header to stop at - the walk runs to the trailer."""
    raw = build_gif([gif_image_block(packed=0x81), gif_xmp_extension(XMP)])
    assert scan(raw).xmp == [XMP]


def test_a_local_colour_table_is_skipped_by_arithmetic():
    """Getting its length wrong would desync the walk and lose everything after it."""
    raw = build_gif([gif_image_block(packed=0x87), gif_xmp_extension(XMP)])
    assert scan(raw).xmp == [XMP]


def test_other_extensions_are_stepped_over():
    raw = build_gif(
        [
            gif_extension(0xF9, b"\x00\x00\x00\x00"),  # graphic control
            gif_extension(0xFE, b"a comment"),  # comment
            gif_extension(0x01, b"plain text"),  # plain text
            gif_xmp_extension(XMP),
        ]
    )
    assert scan(raw).xmp == [XMP]


def test_other_application_extensions_are_ignored():
    """NETSCAPE looping and ICC live in the same block type and say nothing here."""
    raw = build_gif(
        [
            gif_app_extension(b"NETSCAPE2.0", gif_sub_blocks(b"\x01\x00\x00")),
            gif_app_extension(b"ICCRGBG1012", gif_sub_blocks(b"icc-bytes")),
            gif_xmp_extension(XMP),
        ]
    )
    result = scan(raw)
    assert result.xmp == [XMP]
    assert len(result.segments) == 1


def test_87a_is_walked_even_though_it_predates_the_extension():
    result = scan(build_gif([gif_xmp_extension(XMP)], version=b"87a"))
    assert result.xmp == [XMP]
    assert result.notes == ()


def test_an_unknown_version_is_noted_but_still_walked():
    """`b"88a"` rather than `b"92a"`: the magic is `GIF8`, so `GIF92a` never
    sniffs as a GIF in the first place and the walker is not reached at all."""
    result = scan(build_gif([gif_xmp_extension(XMP)], version=b"88a"))
    assert result.xmp == [XMP]
    assert any("unknown GIF version" in note for note in result.notes)


def test_a_version_outside_the_gif8_family_is_not_a_gif_at_all():
    assert scan(build_gif(version=b"92a")).container is None


class TestChunkedXmp:
    """A writer that put the packet through the ordinary sub-block machinery.

    Not what XMP part 3 says, but the length prefixes would otherwise be handed to a
    detector as though they were part of the XML.
    """

    def test_the_packet_is_reassembled(self):
        assert scan(build_gif([gif_xmp_extension(XMP, magic_trailer=False)])).xmp == [XMP]

    def test_it_is_noted_as_non_conformant(self):
        result = scan(build_gif([gif_xmp_extension(XMP, magic_trailer=False)]))
        assert any("no magic trailer" in note for note in result.notes)

    def test_a_packet_longer_than_one_sub_block_is_joined(self):
        big = b"<x:xmpmeta>" + b"x" * 900 + b"</x:xmpmeta>"
        assert scan(build_gif([gif_xmp_extension(big, magic_trailer=False)])).xmp == [big]

    def test_an_empty_block_yields_no_segment(self):
        raw = build_gif([gif_app_extension(b"XMP DataXMP", b"\x00")])
        assert scan(raw).segments == []


class TestBudgets:
    """An oversized block is refused before it is copied, in one shared wording.

    A conformant block is a slice, so `add` weighs it and copies only on acceptance.
    A chunked one has to be joined to exist at all, so its length is walked first and
    put through the same `accepts` predicate - which is what keeps the refusal note
    identical either way, and identical to every other walker's.
    """

    def packet(self, size: int) -> bytes:
        return b"<x:xmpmeta>" + b"x" * size + b"</x:xmpmeta>"

    def big(self, size: int, magic_trailer: bool = True) -> bytes:
        return build_gif([gif_xmp_extension(self.packet(size), magic_trailer=magic_trailer)])

    def test_an_oversized_conformant_packet_is_skipped(self):
        result = scan(self.big(5000), ScanLimits(max_xmp_bytes=1000))
        assert result.segments == []
        assert result.truncated is True
        assert result.notes == (
            "xmp byte budget exhausted (0 of 1000); dropped 5023 from gif:XMP DataXMP",
        )

    def test_an_oversized_chunked_packet_is_skipped(self):
        """The reassembly path is the one that would allocate the most."""
        result = scan(self.big(5000, magic_trailer=False), ScanLimits(max_xmp_bytes=1000))
        assert result.segments == []
        assert result.truncated is True
        assert "no magic trailer" not in " ".join(result.notes), "refused before reassembly"

    def test_both_paths_refuse_in_the_same_words(self):
        """The inconsistency #29 was filed over: two messages for one condition."""
        conformant = scan(self.big(5000), ScanLimits(max_xmp_bytes=1000))
        chunked = scan(self.big(5000, magic_trailer=False), ScanLimits(max_xmp_bytes=1000))
        assert conformant.notes == chunked.notes

    def test_the_measured_length_matches_what_reassembly_produces(self):
        """A mismatch would refuse packets that fit, or admit ones that do not."""
        from thumbor_ai_label.scan.gif import _join_sub_blocks, _sub_block_payload_len

        packet = self.packet(900)
        raw = self.big(900, magic_trailer=False)
        start = raw.index(b"XMP DataXMP") + len(b"XMP DataXMP")
        view = memoryview(raw)
        terminator = raw.index(b"\x00\x3b", start)

        assert _sub_block_payload_len(view, start, terminator) == len(packet)
        assert _join_sub_blocks(view, start, terminator) == packet

    def test_one_that_fits_is_still_read(self):
        result = scan(self.big(100), ScanLimits(max_xmp_bytes=1000))
        assert len(result.xmp) == 1
        assert result.truncated is False


class TestMalformed:
    """Every one of these must produce a note, never an exception."""

    def test_a_buffer_too_short_for_the_screen_descriptor(self):
        result = scan(b"GIF89a")
        assert result.truncated is True
        assert any("too short" in note for note in result.notes)

    def test_an_unknown_block_marker(self):
        result = scan(build_gif([b"\x99"], trailer=False))
        assert result.truncated is True
        assert any("unknown block 0x99" in note for note in result.notes)

    def test_an_extension_with_no_label(self):
        result = scan(build_gif([b"\x21"], trailer=False))
        assert result.truncated is True
        assert any("no label" in note for note in result.notes)

    def test_an_unterminated_extension(self):
        result = scan(build_gif([b"\x21\xfe\x04ab"], trailer=False))
        assert result.truncated is True
        assert any("not terminated" in note for note in result.notes)

    def test_an_application_extension_cut_off_after_its_label(self):
        result = scan(build_gif([b"\x21\xff"], trailer=False))
        assert result.truncated is True
        assert any("no block size" in note for note in result.notes)

    def test_an_application_identifier_running_past_the_buffer(self):
        result = scan(build_gif([b"\x21\xff\x40short"], trailer=False))
        assert result.truncated is True
        assert any("past end of buffer" in note for note in result.notes)

    def test_an_unterminated_application_extension(self):
        result = scan(build_gif([b"\x21\xff\x0bXMP DataXMP\x04ab"], trailer=False))
        assert result.truncated is True
        assert any("not terminated" in note for note in result.notes)

    def test_an_image_descriptor_running_past_the_buffer(self):
        result = scan(build_gif([b"\x2c\x00\x00"], trailer=False))
        assert result.truncated is True
        assert any("image descriptor" in note for note in result.notes)

    def test_image_data_running_past_the_buffer(self):
        """The descriptor fits but the LZW code size is off the end."""
        result = scan(build_gif([b"\x2c" + b"\x00" * 9], trailer=False))
        assert result.truncated is True
        assert any("image data" in note for note in result.notes)

    def test_unterminated_image_data(self):
        result = scan(build_gif([b"\x2c" + b"\x00" * 9 + b"\x08\x04ab"], trailer=False))
        assert result.truncated is True
        assert any("not terminated" in note for note in result.notes)

    def test_a_missing_trailer(self):
        result = scan(build_gif([gif_image_block()], trailer=False))
        assert result.truncated is True
        assert any("before the GIF trailer" in note for note in result.notes)

    def test_metadata_found_before_the_damage_is_kept(self):
        """The fail-closed policy keys off has_any_metadata, so it must survive."""
        result = scan(build_gif([gif_xmp_extension(XMP), b"\x99"], trailer=False))
        assert result.xmp == [XMP]
        assert result.has_any_metadata is True
        assert result.truncated is True
