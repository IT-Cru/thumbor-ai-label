"""EXIF detector.

**EXIF has no field that means "this image is AI".** Unlike IPTC, which defines
`DigitalSourceType` as a controlled vocabulary, nothing in the EXIF specification
carries a provenance assertion - there is no standard tag to read. What EXIF has is
free-text fields that tools happen to write their own name into: Software,
ProcessingSoftware, ImageDescription, UserComment.

So this detector reads *standard* EXIF tags - not vendor-private MakerNote data -
and matches their contents against known generator names. The tags are standard;
the matching vocabulary is what is vendor-specific. That distinction is why the
verdict is always LOW confidence: an assertion is being inferred from a tool name,
not read from a field that means what we need it to mean.

Both IFD0 and the Exif sub-IFD are walked, since UserComment - where generation
parameters are sometimes written - lives in the latter.
"""

from __future__ import annotations

import struct

from ..scan import ScanResult, SegmentKind
from .types import Confidence, Detection, SourceType

NAME = "exif"
REQUIRES = frozenset({SegmentKind.EXIF})

TAG_PROCESSING_SOFTWARE = 0x000B
TAG_IMAGE_DESCRIPTION = 0x010E
TAG_MAKE = 0x010F
TAG_MODEL = 0x0110
TAG_SOFTWARE = 0x0131
TAG_ARTIST = 0x013B
TAG_COPYRIGHT = 0x8298
TAG_EXIF_IFD_POINTER = 0x8769
TAG_USER_COMMENT = 0x9286
TAG_XP_COMMENT = 0x9C9C

#: Read in this order; the order also fixes how evidence is presented.
READ_TAGS: tuple[tuple[int, str], ...] = (
    (TAG_SOFTWARE, "Software"),
    (TAG_PROCESSING_SOFTWARE, "ProcessingSoftware"),
    (TAG_MAKE, "Make"),
    (TAG_MODEL, "Model"),
    (TAG_IMAGE_DESCRIPTION, "ImageDescription"),
    (TAG_USER_COMMENT, "UserComment"),
    (TAG_XP_COMMENT, "XPComment"),
    (TAG_ARTIST, "Artist"),
    (TAG_COPYRIGHT, "Copyright"),
)
TAG_NAMES = dict(READ_TAGS)

TYPE_BYTE = 1
TYPE_ASCII = 2
TYPE_LONG = 4
TYPE_UNDEFINED = 7

MAX_IFD_ENTRIES = 512
MAX_VALUE_BYTES = 16384
MAX_EVIDENCE_CHARS = 120

_COMMENT_CHARSETS = (
    (b"ASCII\x00\x00\x00", "ascii"),
    (b"UNICODE\x00", None),  # UTF-16, endianness follows the TIFF byte order
    (b"JIS\x00\x00\x00\x00\x00", "shift_jis"),
    (b"\x00" * 8, "latin-1"),
)

#: (substring, state, generator label). Matched case-insensitively.
#: High precision beats coverage: a false positive labels a real photograph.
VENDOR_PATTERNS: tuple[tuple[str, SourceType, str], ...] = (
    ("midjourney", SourceType.AI_GENERATED, "Midjourney"),
    ("stable diffusion", SourceType.AI_GENERATED, "Stable Diffusion"),
    ("automatic1111", SourceType.AI_GENERATED, "Stable Diffusion"),
    ("comfyui", SourceType.AI_GENERATED, "ComfyUI"),
    ("novelai", SourceType.AI_GENERATED, "NovelAI"),
    ("dall-e", SourceType.AI_GENERATED, "DALL-E"),
    ("dall·e", SourceType.AI_GENERATED, "DALL-E"),
    ("adobe firefly", SourceType.AI_GENERATED, "Adobe Firefly"),
    ("google imagen", SourceType.AI_GENERATED, "Google Imagen"),
    ("leonardo.ai", SourceType.AI_GENERATED, "Leonardo.Ai"),
    ("ideogram", SourceType.AI_GENERATED, "Ideogram"),
    ("magic editor", SourceType.AI_MANIPULATED, "Google Magic Editor"),
    ("generative fill", SourceType.AI_MANIPULATED, "Adobe Generative Fill"),
    ("generative expand", SourceType.AI_MANIPULATED, "Adobe Generative Expand"),
)


def _decode_value(tag: int, field_type: int, raw: bytes, endian: str) -> str:
    if field_type == TYPE_ASCII:
        return raw.split(b"\x00", 1)[0].decode("utf-8", errors="replace").strip()

    if tag == TAG_USER_COMMENT and field_type in (TYPE_UNDEFINED, TYPE_BYTE):
        # The spec says UserComment is UNDEFINED, but Pillow writes it as BYTE and
        # both turn up in real files. The payload is identical either way, so accept
        # both rather than silently skipping half the encoders in the world.
        #
        # UserComment is prefixed by an 8-byte character-set marker.
        for marker, encoding in _COMMENT_CHARSETS:
            if raw[:8] == marker:
                body = raw[8:]
                if encoding is None:
                    encoding = "utf-16-le" if endian == "<" else "utf-16-be"
                return body.decode(encoding, errors="replace").rstrip("\x00").strip()
        return ""

    if field_type == TYPE_BYTE and tag == TAG_XP_COMMENT:
        # Windows XP* tags are UTF-16LE regardless of the TIFF byte order.
        return raw.decode("utf-16-le", errors="replace").rstrip("\x00").strip()

    return ""


def _walk_ifd(
    blob: bytes, endian: str, offset: int, values: dict[int, str]
) -> int | None:
    """Read the tags of interest from one IFD. Returns the Exif sub-IFD offset if seen."""
    if not 8 <= offset < len(blob) - 2:
        return None

    (count,) = struct.unpack(endian + "H", blob[offset : offset + 2])
    count = min(count, MAX_IFD_ENTRIES)

    sub_ifd = None
    base = offset + 2
    for index in range(count):
        entry = base + index * 12
        if entry + 12 > len(blob):
            break

        tag, field_type, length = struct.unpack(endian + "HHI", blob[entry : entry + 8])

        if tag == TAG_EXIF_IFD_POINTER and field_type == TYPE_LONG and length == 1:
            (sub_ifd,) = struct.unpack(endian + "I", blob[entry + 8 : entry + 12])
            continue

        if tag not in TAG_NAMES or tag in values:
            continue
        if not 0 < length <= MAX_VALUE_BYTES:
            continue

        if length <= 4:
            raw = blob[entry + 8 : entry + 8 + length]
        else:
            (value_offset,) = struct.unpack(endian + "I", blob[entry + 8 : entry + 12])
            if value_offset + length > len(blob):
                continue
            raw = blob[value_offset : value_offset + length]

        text = _decode_value(tag, field_type, raw, endian)
        if text:
            values[tag] = text

    return sub_ifd


def _read_tags(blob: bytes) -> dict[int, str]:
    """Pull the tags of interest out of IFD0 and the Exif sub-IFD."""
    if len(blob) < 8:
        return {}

    byte_order = blob[:2]
    if byte_order == b"II":
        endian = "<"
    elif byte_order == b"MM":
        endian = ">"
    else:
        return {}

    # Every unpack below is preceded by a bounds check that guarantees the slice
    # length, so struct.error cannot arise and is not caught defensively.
    magic, ifd0 = struct.unpack(endian + "HI", blob[2:8])
    if magic != 42:
        return {}

    values: dict[int, str] = {}
    sub_ifd = _walk_ifd(blob, endian, ifd0, values)
    if sub_ifd is not None and sub_ifd != ifd0:
        # Only the one nested IFD is followed, so a pointer loop cannot spin.
        _walk_ifd(blob, endian, sub_ifd, values)
    return values


def detect(result: ScanResult) -> Detection | None:
    for blob in result.exif:
        try:
            tags = _read_tags(blob)
        except Exception:  # noqa: BLE001, S112
            # A malformed blob must not stop us checking the next one, and logging per
            # blob would spam the request path on hostile input. The absence of tags is
            # itself the signal.
            continue
        if not tags:
            continue

        for needle, source_type, generator in VENDOR_PATTERNS:
            for tag, label in READ_TAGS:
                text = tags.get(tag)
                if text and needle in text.lower():
                    # Evidence names the tag and is tightly capped: UserComment can
                    # hold a whole generation prompt, which does not belong in logs
                    # or on a public meta endpoint.
                    return Detection(
                        source_type=source_type,
                        confidence=Confidence.LOW,
                        detector=NAME,
                        evidence=f"{label}: {text[:MAX_EVIDENCE_CHARS]}",
                        generator=generator,
                    )

    return None
