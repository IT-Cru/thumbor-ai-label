from __future__ import annotations

import struct

import pytest

from thumbor_ai_label.detect import Confidence, SourceType
from thumbor_ai_label.detect import exif as detector
from thumbor_ai_label.scan import ScanLimits, ScanResult, SegmentKind

TAG_SOFTWARE = 0x0131
TAG_MAKE = 0x010F
TAG_MODEL = 0x0110


def build_tiff(ifd0, sub=None, endian: str = "<") -> bytes:
    """A TIFF blob from explicit (tag, type, raw) entries, with an optional Exif sub-IFD."""
    blob = bytearray()
    entry_count = len(ifd0) + (1 if sub is not None else 0)
    ifd0_offset = 8
    ifd0_size = 2 + 12 * entry_count + 4
    sub_offset = ifd0_offset + ifd0_size
    sub_size = (2 + 12 * len(sub) + 4) if sub is not None else 0
    data_offset = sub_offset + sub_size

    def entries(items):
        out = b""
        for tag, field_type, raw in items:
            if len(raw) <= 4:
                payload = raw.ljust(4, b"\x00")
            else:
                payload = struct.pack(endian + "I", data_offset + len(blob))
                blob.extend(raw)
            out += struct.pack(endian + "HHI", tag, field_type, len(raw)) + payload
        return out

    body0 = entries(ifd0)
    if sub is not None:
        body0 += struct.pack(endian + "HHI", 0x8769, 4, 1) + struct.pack(endian + "I", sub_offset)
    body_sub = entries(sub) if sub is not None else b""

    out = (b"II" if endian == "<" else b"MM") + struct.pack(endian + "HI", 42, ifd0_offset)
    out += struct.pack(endian + "H", entry_count) + body0 + struct.pack(endian + "I", 0)
    if sub is not None:
        out += struct.pack(endian + "H", len(sub)) + body_sub + struct.pack(endian + "I", 0)
    return out + bytes(blob)


def tiff(tags: dict, endian: str = "<") -> bytes:
    """Convenience wrapper for plain ASCII tags in IFD0."""
    return build_tiff(
        [(tag, 2, value.encode("utf-8") + b"\x00") for tag, value in sorted(tags.items())],
        endian=endian,
    )


def user_comment(text: str, charset: bytes = b"ASCII\x00\x00\x00") -> bytes:
    if charset == b"UNICODE\x00":
        return charset + text.encode("utf-16-le")
    return charset + text.encode("utf-8")


def scanned(blob: bytes) -> ScanResult:
    result = ScanResult()
    result.add(SegmentKind.EXIF, blob, "test", ScanLimits())
    return result


class TestVendorMatching:
    @pytest.mark.parametrize(
        "software,expected,generator",
        [
            ("Midjourney v6.1", SourceType.AI_GENERATED, "Midjourney"),
            ("Stable Diffusion WebUI", SourceType.AI_GENERATED, "Stable Diffusion"),
            ("ComfyUI", SourceType.AI_GENERATED, "ComfyUI"),
            ("Adobe Firefly", SourceType.AI_GENERATED, "Adobe Firefly"),
            ("Google Magic Editor", SourceType.AI_MANIPULATED, "Google Magic Editor"),
            ("Adobe Photoshop 25.0 Generative Fill", SourceType.AI_MANIPULATED, "Adobe Generative Fill"),
        ],
    )
    def test_known_generators(self, software, expected, generator):
        found = detector.detect(scanned(tiff({TAG_SOFTWARE: software})))
        assert found.source_type is expected
        assert found.generator == generator

    def test_always_reported_at_low_confidence(self):
        found = detector.detect(scanned(tiff({TAG_SOFTWARE: "Midjourney"})))
        assert found.confidence is Confidence.LOW
        assert found.is_conclusive is False

    def test_matching_is_case_insensitive(self):
        assert detector.detect(scanned(tiff({TAG_SOFTWARE: "MIDJOURNEY"}))).generator == "Midjourney"

    def test_matches_across_any_read_tag(self):
        found = detector.detect(scanned(tiff({TAG_MAKE: "Midjourney", TAG_MODEL: "v6"})))
        assert found.source_type is SourceType.AI_GENERATED

    def test_evidence_carries_the_matched_text(self):
        found = detector.detect(scanned(tiff({TAG_SOFTWARE: "Midjourney v6.1"})))
        assert "Midjourney v6.1" in found.evidence


class TestPrecision:
    @pytest.mark.parametrize(
        "software",
        [
            "Adobe Photoshop 25.0",
            "Adobe Lightroom Classic 13.2",
            "GIMP 2.10.36",
            "darktable 4.6.1",
            "Capture One 23",
            "iPhone 15 Pro",
            "",
        ],
    )
    def test_ordinary_editors_never_match(self, software):
        """A false positive here labels a real photograph, so precision beats recall."""
        assert detector.detect(scanned(tiff({TAG_SOFTWARE: software}))) is None

    def test_no_exif_at_all(self):
        assert detector.detect(ScanResult()) is None

    def test_exif_without_the_tags_of_interest(self):
        assert detector.detect(scanned(tiff({0x0112: "1"}))) is None


class TestParsing:
    @pytest.mark.parametrize("endian", ["<", ">"])
    def test_both_byte_orders(self, endian):
        blob = tiff({TAG_SOFTWARE: "Midjourney v6"}, endian=endian)
        assert detector.detect(scanned(blob)).source_type is SourceType.AI_GENERATED

    def test_short_value_stored_inline(self):
        """Values of 4 bytes or fewer live in the entry, not at an offset."""
        blob = tiff({TAG_MAKE: "ai", TAG_SOFTWARE: "Midjourney"})
        assert detector.detect(scanned(blob)) is not None

    def test_real_pillow_exif_round_trip(self):
        PIL = pytest.importorskip("PIL")
        import io

        from PIL import Image

        from thumbor_ai_label.scan import scan

        image = Image.new("RGB", (8, 8))
        tags = image.getexif()
        tags[TAG_SOFTWARE] = "Midjourney v6.1"
        buf = io.BytesIO()
        image.save(buf, "JPEG", exif=tags)

        found = detector.detect(scan(buf.getvalue()))
        assert found.source_type is SourceType.AI_GENERATED
        assert found.generator == "Midjourney"


class TestMalformed:
    @pytest.mark.parametrize(
        "blob",
        [
            b"",
            b"XX",
            b"II",
            b"II*\x00",
            b"ZZ*\x00\x08\x00\x00\x00",
            b"II\x2b\x00\x08\x00\x00\x00",  # BigTIFF magic, not supported
            b"II*\x00\xff\xff\xff\xff",  # IFD offset past the end
        ],
    )
    def test_degenerate_blobs_yield_nothing(self, blob):
        assert detector.detect(scanned(blob)) is None

    def test_entry_count_larger_than_the_buffer(self):
        blob = b"II" + struct.pack("<HI", 42, 8) + struct.pack("<H", 60000)
        assert detector.detect(scanned(blob)) is None

    def test_value_offset_past_the_end_is_skipped(self):
        blob = bytearray(tiff({TAG_SOFTWARE: "Midjourney v6.1"}))
        entry = 8 + 2
        blob[entry + 8 : entry + 12] = struct.pack("<I", 0xFFFFFF)
        assert detector.detect(scanned(bytes(blob))) is None

    def test_truncation_at_every_offset_never_raises(self):
        blob = tiff({TAG_SOFTWARE: "Midjourney v6.1", TAG_MAKE: "Acme"})
        for cut in range(len(blob) + 1):
            detector.detect(scanned(blob[:cut]))


class TestBounds:
    def test_zero_length_value_is_skipped(self):
        blob = bytearray(tiff({TAG_SOFTWARE: "Midjourney v6.1"}))
        entry = 8 + 2
        blob[entry + 4 : entry + 8] = struct.pack("<I", 0)
        assert detector.detect(scanned(bytes(blob))) is None

    def test_absurd_value_length_is_skipped(self):
        blob = bytearray(tiff({TAG_SOFTWARE: "Midjourney v6.1"}))
        entry = 8 + 2
        blob[entry + 4 : entry + 8] = struct.pack("<I", 0xFFFFFFF)
        assert detector.detect(scanned(bytes(blob))) is None

    def test_entry_count_is_capped(self):
        """A declared count far past the buffer stops at the buffer, not the count."""
        blob = tiff({TAG_SOFTWARE: "Midjourney v6.1"})
        blob = blob[:8] + struct.pack("<H", 60000) + blob[10:]
        assert detector.detect(scanned(blob)) is not None

    def test_an_unexpected_parser_error_is_contained(self, monkeypatch):
        def explode(_blob):
            raise RuntimeError("parser bug")

        monkeypatch.setattr(detector, "_read_tags", explode)
        assert detector.detect(scanned(tiff({TAG_SOFTWARE: "Midjourney"}))) is None


class TestStandardTagCoverage:
    """EXIF has no AI field, so every readable signal is a free-text tag."""

    def test_processing_software(self):
        blob = tiff({detector.TAG_PROCESSING_SOFTWARE: "Adobe Firefly"})
        assert detector.detect(scanned(blob)).generator == "Adobe Firefly"

    def test_image_description(self):
        blob = tiff({detector.TAG_IMAGE_DESCRIPTION: "made with Midjourney"})
        assert detector.detect(scanned(blob)).source_type is SourceType.AI_GENERATED

    def test_user_comment_in_the_exif_sub_ifd(self):
        """UserComment lives in the sub-IFD, so IFD0 alone would miss it."""
        blob = build_tiff(
            [(TAG_MAKE, 2, b"Acme\x00")],
            sub=[(detector.TAG_USER_COMMENT, 7, user_comment("Steps: 20, Model: Stable Diffusion"))],
        )
        found = detector.detect(scanned(blob))
        assert found.source_type is SourceType.AI_GENERATED
        assert found.evidence.startswith("UserComment: ")

    def test_user_comment_with_unicode_charset(self):
        blob = build_tiff(
            [],
            sub=[
                (
                    detector.TAG_USER_COMMENT,
                    7,
                    user_comment("generated by ComfyUI", charset=b"UNICODE\x00"),
                )
            ],
        )
        assert detector.detect(scanned(blob)).generator == "ComfyUI"

    def test_user_comment_with_unknown_charset_is_ignored(self):
        blob = build_tiff([], sub=[(detector.TAG_USER_COMMENT, 7, b"WEIRD\x00\x00\x00Midjourney")])
        assert detector.detect(scanned(blob)) is None

    def test_xp_comment_is_utf16(self):
        raw = "Adobe Firefly".encode("utf-16-le") + b"\x00\x00"
        blob = build_tiff([(detector.TAG_XP_COMMENT, 1, raw)])
        assert detector.detect(scanned(blob)).generator == "Adobe Firefly"

    def test_sub_ifd_pointing_at_itself_does_not_loop(self):
        blob = bytearray(build_tiff([(TAG_MAKE, 2, b"Acme\x00")], sub=[]))
        # Repoint the sub-IFD at IFD0.
        pointer_entry = 8 + 2 + 12
        blob[pointer_entry + 8 : pointer_entry + 12] = struct.pack("<I", 8)
        assert detector.detect(scanned(bytes(blob))) is None


class TestEvidence:
    def test_evidence_names_the_tag_it_came_from(self):
        found = detector.detect(scanned(tiff({TAG_SOFTWARE: "Midjourney v6.1"})))
        assert found.evidence == "Software: Midjourney v6.1"

    def test_a_long_generation_prompt_is_not_dumped_wholesale(self):
        """UserComment can hold a whole prompt; it must not reach logs or /meta."""
        prompt = "Midjourney prompt: " + "a very private and lengthy description " * 40
        blob = build_tiff([], sub=[(detector.TAG_USER_COMMENT, 7, user_comment(prompt))])
        found = detector.detect(scanned(blob))
        assert len(found.evidence) <= detector.MAX_EVIDENCE_CHARS + len("UserComment: ")
        assert len(found.evidence) < len(prompt) / 10
        assert found.source_type is SourceType.AI_GENERATED


def test_a_tag_of_an_unhandled_type_is_ignored():
    """Only ASCII, the UserComment blob and the UTF-16 XP tags carry readable text."""
    blob = build_tiff([(TAG_SOFTWARE, 3, struct.pack("<HH", 1, 2))])  # SHORT
    assert detector.detect(scanned(blob)) is None


class TestUserCommentFieldTypes:
    """The spec says UNDEFINED; real encoders disagree.

    Caught by the test-image corpus, not by hand-built fixtures - those all used the
    spec-conformant type, so the gap was invisible until real encoder output hit it.
    """

    PROMPT = "Steps: 20, Sampler: Euler, Model: Stable Diffusion XL"

    @pytest.mark.parametrize("field_type", [7, 1], ids=["UNDEFINED (spec)", "BYTE (Pillow)"])
    def test_both_field_types_are_read(self, field_type):
        blob = build_tiff([], sub=[(detector.TAG_USER_COMMENT, field_type, user_comment(self.PROMPT))])
        found = detector.detect(scanned(blob))
        assert found is not None, "UserComment as type {} was skipped".format(field_type)
        assert found.source_type is SourceType.AI_GENERATED

    def test_a_real_pillow_written_user_comment_round_trips(self):
        PIL = pytest.importorskip("PIL")
        import io

        from PIL import Image

        from thumbor_ai_label.scan import scan

        image = Image.new("RGB", (16, 16))
        data = image.getexif()
        sub = data.get_ifd(0x8769)
        sub[detector.TAG_USER_COMMENT] = b"ASCII\x00\x00\x00" + self.PROMPT.encode()
        buf = io.BytesIO()
        image.save(buf, "JPEG", exif=data)

        found = detector.detect(scan(buf.getvalue()))
        assert found is not None
        assert found.generator == "Stable Diffusion"
