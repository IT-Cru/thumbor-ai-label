from __future__ import annotations

import struct

import pytest

from thumbor_ai_label.scan import Container, ScanLimits, SegmentKind, scan

from .builders import (
    app,
    app1_exif,
    app1_xmp,
    app1_xmp_ext,
    app11_jumbf,
    build_jpeg,
)

XMP = b'<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF/></x:xmpmeta>'
TIFF = b"II*\x00\x08\x00\x00\x00" + b"\x00" * 8


def test_recognises_container():
    assert scan(build_jpeg()).container is Container.JPEG


def test_bare_jpeg_has_no_metadata():
    result = scan(build_jpeg())
    assert result.segments == []
    assert result.has_any_metadata is False
    assert result.truncated is False


def test_extracts_xmp_without_its_framing():
    result = scan(build_jpeg([app1_xmp(XMP)]))
    assert result.xmp == [XMP]
    assert result.segments[0].origin == "jpeg:APP1/xmp"


def test_extracts_exif_starting_at_the_tiff_header():
    result = scan(build_jpeg([app1_exif(TIFF)]))
    assert result.exif == [TIFF]


def test_extracts_both_xmp_and_exif():
    result = scan(build_jpeg([app1_exif(TIFF), app1_xmp(XMP)]))
    assert result.exif == [TIFF]
    assert result.xmp == [XMP]
    assert set(result.kinds()) == {SegmentKind.EXIF, SegmentKind.XMP}


def test_ignores_unrelated_app_segments():
    icc = app(0xE2, b"ICC_PROFILE\x00" + b"\x00" * 20)
    comment = app(0xFE, b"a comment")
    result = scan(build_jpeg([icc, comment, app1_xmp(XMP)]))
    assert result.xmp == [XMP]
    assert result.truncated is False


def test_tolerates_fill_bytes_before_a_marker():
    raw = build_jpeg([b"\xff" + app1_xmp(XMP)])
    assert scan(raw).xmp == [XMP]


def test_stops_at_the_scan_header():
    """Metadata after SOS is not reached - that is the performance contract."""
    hidden = app1_xmp(b"<late/>")
    raw = build_jpeg([app1_xmp(XMP)], entropy=b"\x11" * 8 + hidden)
    result = scan(raw)
    assert result.xmp == [XMP]


def test_entropy_data_containing_marker_lookalikes_is_never_walked():
    # 0xFFD8 inside entropy data would derail a naive scanner.
    raw = build_jpeg([app1_xmp(XMP)], entropy=b"\xff\x00\xff\xd8\xff\xe1\x00\x04")
    result = scan(raw)
    assert result.xmp == [XMP]
    assert result.truncated is False


class TestExtendedXmp:
    GUID = b"A" * 32

    def test_reassembles_chunks_in_offset_order(self):
        body = b"<big>" + b"x" * 100 + b"</big>"
        first, second = body[:40], body[40:]
        raw = build_jpeg(
            [
                app1_xmp_ext(self.GUID, len(body), 40, second),
                app1_xmp_ext(self.GUID, len(body), 0, first),
            ]
        )
        result = scan(raw)
        assert result.xmp == [body]
        assert result.truncated is False

    def test_keeps_the_contiguous_prefix_when_a_chunk_is_missing(self):
        body = b"y" * 90
        raw = build_jpeg(
            [
                app1_xmp_ext(self.GUID, len(body), 0, body[:30]),
                app1_xmp_ext(self.GUID, len(body), 60, body[60:]),
            ]
        )
        result = scan(raw)
        assert result.xmp == [body[:30]]
        assert result.truncated is True
        assert any("gap" in note for note in result.notes)

    def test_separate_guids_stay_separate(self):
        raw = build_jpeg(
            [
                app1_xmp_ext(b"A" * 32, 4, 0, b"aaaa"),
                app1_xmp_ext(b"B" * 32, 4, 0, b"bbbb"),
            ]
        )
        assert sorted(scan(raw).xmp) == [b"aaaa", b"bbbb"]

    def test_oversized_declaration_is_refused_before_allocating(self):
        limits = ScanLimits(max_xmp_bytes=100)
        raw = build_jpeg([app1_xmp_ext(self.GUID, 50_000_000, 0, b"z" * 10)])
        result = scan(raw, limits)
        assert result.xmp == []
        assert result.truncated is True

    def test_header_shorter_than_its_own_fields(self):
        raw = build_jpeg([app(0xE1, b"http://ns.adobe.com/xmp/extension/\x00" + b"A" * 8)])
        result = scan(raw)
        assert result.xmp == []
        assert result.truncated is True


class TestJumbf:
    def test_single_packet_keeps_the_box_header(self):
        result = scan(build_jpeg([app11_jumbf(b"manifest-bytes")]))
        assert len(result.jumbf) == 1
        box = result.jumbf[0]
        assert box[4:8] == b"jumb"
        assert box.endswith(b"manifest-bytes")

    def test_packets_reassemble_in_sequence_order(self):
        raw = build_jpeg(
            [
                app11_jumbf(b"-second", sequence=2),
                app11_jumbf(b"first", sequence=1),
            ]
        )
        assert scan(raw).jumbf[0].endswith(b"first-second")

    def test_box_instances_stay_separate(self):
        raw = build_jpeg(
            [
                app11_jumbf(b"one", instance=1),
                app11_jumbf(b"two", instance=2),
            ]
        )
        boxes = scan(raw).jumbf
        assert len(boxes) == 2
        assert boxes[0].endswith(b"one") and boxes[1].endswith(b"two")

    def test_duplicate_sequence_is_reported_not_appended(self):
        raw = build_jpeg([app11_jumbf(b"one", sequence=1), app11_jumbf(b"dup", sequence=1)])
        result = scan(raw)
        assert result.jumbf[0].endswith(b"one")
        assert any("duplicate" in note for note in result.notes)

    def test_app11_without_the_jp_marker_is_ignored(self):
        raw = build_jpeg([app(0xEB, b"XX" + b"\x00" * 20)])
        assert scan(raw).jumbf == []


class TestMalformed:
    def test_segment_length_below_the_minimum(self):
        raw = b"\xff\xd8" + b"\xff\xe1" + struct.pack(">H", 1) + b"\xff\xd9"
        result = scan(raw)
        assert result.truncated is True
        assert result.container is Container.JPEG

    def test_segment_running_past_the_buffer(self):
        raw = b"\xff\xd8" + b"\xff\xe1" + struct.pack(">H", 9000) + b"short"
        result = scan(raw)
        assert result.truncated is True
        assert any("past end" in note for note in result.notes)

    def test_desync_is_reported(self):
        raw = b"\xff\xd8\xff" + b"\xe1\x00\x04ab" + b"garbage-not-a-marker"
        result = scan(raw)
        assert result.truncated is True

    def test_metadata_before_a_broken_segment_is_still_returned(self):
        raw = b"\xff\xd8" + app1_xmp(XMP) + b"\xff\xe1" + struct.pack(">H", 9000) + b"x"
        result = scan(raw)
        assert result.xmp == [XMP]
        assert result.truncated is True


def test_scan_past_sos_is_declined_rather_than_silently_ignored():
    raw = build_jpeg([app1_xmp(XMP)])
    result = scan(raw, ScanLimits(scan_past_sos=True))
    assert any("scan_past_sos" in note for note in result.notes)


@pytest.mark.parametrize(
    "limits,expected",
    [
        (ScanLimits(max_xmp_bytes=10), 0),
        (ScanLimits(max_xmp_bytes=10_000), 1),
    ],
)
def test_xmp_budget_is_enforced(limits, expected):
    result = scan(build_jpeg([app1_xmp(b"z" * 500)]), limits)
    assert len(result.xmp) == expected


def test_segment_count_limit_stops_collection():
    segments = [app1_xmp(b"<a/>") for _ in range(20)]
    result = scan(build_jpeg(segments), ScanLimits(max_segments=5))
    assert len(result.segments) == 5
    assert result.truncated is True


def test_extended_xmp_with_no_chunk_at_offset_zero_yields_nothing():
    """Without the opening chunk there is no valid prefix to hand over."""
    raw = build_jpeg([app1_xmp_ext(b"C" * 32, 100, 50, b"tail-only")])
    result = scan(raw)
    assert result.xmp == []
    assert result.truncated is True


def test_scan_accepts_a_non_byte_memoryview():
    import array

    raw = build_jpeg([app1_xmp(XMP)])
    words = array.array("I")
    padded = raw + b"\x00" * (-len(raw) % 4)
    words.frombytes(padded)
    assert scan(memoryview(words)).xmp == [XMP]
