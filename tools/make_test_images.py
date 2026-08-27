"""Generate a corpus of test images for validating the plugin end to end.

    python tools/make_test_images.py

Writes to tests/images/ : the images, plus manifest.json recording what each one is
expected to produce. `tools/verify_test_images.py` checks reality against that.

These images are SYNTHETIC. They are geometric patterns carrying hand-written
provenance metadata, not output from any AI system. A file whose EXIF reads
"Midjourney" was not made by Midjourney - it exists to prove the parser reads that
tag. Nothing here should be mistaken for genuine AI-generated content or for a
genuine provenance record.

That is also this corpus's limitation, and it is worth stating plainly: it proves the
plugin behaves correctly on *well-formed* metadata that this project wrote itself. It
cannot prove the plugin copes with what real generators actually emit. Only real
files from DALL-E, Firefly, Midjourney, Pixel and the rest can do that.
"""

from __future__ import annotations

import io
import json
import pathlib
import struct
from collections.abc import Callable
from dataclasses import dataclass

from PIL import Image, ImageDraw, ImageFont

OUT = pathlib.Path(__file__).resolve().parent.parent / "tests" / "images"

CV = "http://cv.iptc.org/newscodes/digitalsourcetype/"
IPTC_NS = "http://iptc.org/std/Iptc4xmpExt/2008-02-29/"
XMP_SIG = b"http://ns.adobe.com/xap/1.0/\x00"
XMP_EXT_SIG = b"http://ns.adobe.com/xmp/extension/\x00"

PALETTES = [
    ((58, 92, 140), (120, 160, 190), (34, 52, 44)),
    ((140, 76, 58), (198, 150, 110), (60, 40, 32)),
    ((70, 110, 78), (150, 185, 140), (38, 56, 40)),
    ((96, 72, 128), (168, 148, 200), (44, 34, 60)),
    ((150, 120, 40), (210, 190, 120), (70, 56, 24)),
]


def base_image(index: int, size=(800, 600), dark=False, caption="") -> Image.Image:
    """A distinguishable synthetic scene, captioned top-left so it cannot collide
    with the label, which is drawn bottom-right by default."""
    sky, haze, ground = PALETTES[index % len(PALETTES)]
    if dark:
        sky = tuple(c // 3 for c in sky)
        haze = tuple(c // 3 for c in haze)
        ground = tuple(c // 3 for c in ground)

    width, height = size
    image = Image.new("RGB", size)
    draw = ImageDraw.Draw(image)
    for y in range(height):
        t = y / height
        draw.line(
            [(0, y), (width, y)],
            fill=tuple(round(sky[i] + (haze[i] - sky[i]) * t) for i in range(3)),
        )
    draw.ellipse(
        [width * 0.70, height * 0.10, width * 0.86, height * 0.31],
        fill=(250, 244, 214) if not dark else (190, 184, 160),
    )
    offset = (index % 3) * 0.06
    draw.polygon(
        [(0, height), (width * (0.34 + offset), height * 0.44), (width * 0.66, height)],
        fill=ground,
    )
    draw.polygon(
        [(width * 0.42, height), (width * (0.74 - offset), height * 0.54), (width, height)],
        fill=tuple(max(0, c - 14) for c in ground),
    )

    if caption:
        font = ImageFont.load_default(size=max(13, width // 46))
        pad = max(6, width // 90)
        box = draw.textbbox((pad, pad), caption, font=font)
        draw.rectangle(
            [box[0] - pad // 2, box[1] - pad // 2, box[2] + pad // 2, box[3] + pad // 2],
            fill=(0, 0, 0),
        )
        draw.text((pad, pad), caption, fill=(255, 255, 255), font=font)
    return image


def xmp_packet(term: str | None = None, extra: str = "", full_uri: bool = True) -> bytes:
    field = ""
    if term is not None:
        value = (CV + term) if full_uri else term
        field = f' Iptc4xmpExt:DigitalSourceType="{value}"'
    return (
        '<?xpacket begin="﻿" id="W5M0MpCehiHzreSzNTczkc9d"?>'
        '<x:xmpmeta xmlns:x="adobe:ns:meta/">'
        '<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
        f'<rdf:Description rdf:about="" xmlns:Iptc4xmpExt="{IPTC_NS}" '
        f'xmlns:dc="http://purl.org/dc/elements/1.1/"{field}>{extra}</rdf:Description>'
        "</rdf:RDF></x:xmpmeta>"
        '<?xpacket end="w"?>'
    ).encode()


def encode(image, fmt="JPEG", **kwargs) -> bytes:
    buffer = io.BytesIO()
    if fmt == "JPEG":
        kwargs.setdefault("quality", 92)
    image.save(buffer, fmt, **kwargs)
    return buffer.getvalue()


def splice_app1(jpeg: bytes, payloads: list[bytes]) -> bytes:
    """Insert APP1 segments straight after SOI, for cases Pillow will not write."""
    out = jpeg[:2]
    for payload in payloads:
        out += b"\xff\xe1" + struct.pack(">H", len(payload) + 2) + payload
    return out + jpeg[2:]


def exif_for(image, tags):
    """tags is {int_tag: value}. Not **kwargs - keyword names would arrive as strings
    and Pillow needs integer tag ids."""
    data = image.getexif()
    for tag, value in tags.items():
        data[tag] = value
    return data


TAG_SOFTWARE = 0x0131
TAG_MAKE = 0x010F
TAG_MODEL = 0x0110


@dataclass(frozen=True)
class Case:
    """One test image: how to build it, and what it should produce.

    Expected values are the resulting `label` state, or None for "no label drawn".
    Both policies are always stated explicitly rather than defaulting one to the
    other: the pair is the point of the table, and cases 13 and 14 exist precisely
    because they diverge.
    """

    file: str
    description: str
    strict: str | None
    relaxed: str | None
    build: Callable[[], bytes]
    notes: str = ""

    def as_manifest_entry(self, payload: bytes, size: tuple[int, int]) -> dict:
        return {
            "file": self.file,
            "description": self.description,
            "size": list(size),
            "bytes": len(payload),
            "expected": {"strict": self.strict, "relaxed": self.relaxed},
            "notes": self.notes,
        }


def iptc_jpeg(index, term, caption, full_uri=True, size=(800, 600), dark=False):
    image = base_image(index, size=size, dark=dark, caption=caption)
    return encode(image, "JPEG", xmp=xmp_packet(term, full_uri=full_uri))


# -- Builders needing more than an expression -----------------------------


def _exif_midjourney() -> bytes:
    image = base_image(3, caption="09 expect: AI GENERATED (low conf)")
    return encode(image, "JPEG", exif=exif_for(image, {TAG_SOFTWARE: "Midjourney v6.1"}))


def _exif_photoshop() -> bytes:
    image = base_image(4, caption="10 expect: strict UNKNOWN / relaxed NO label")
    return encode(image, "JPEG", exif=exif_for(image, {TAG_SOFTWARE: "Adobe Photoshop 25.0"}))


def _exif_user_comment() -> bytes:
    image = base_image(0, caption="11 expect: AI GENERATED (low conf)")
    data = image.getexif()
    data[TAG_MAKE] = "TestCorp"
    sub = data.get_ifd(0x8769)
    sub[0x9286] = b"ASCII\x00\x00\x00Steps: 20, Sampler: Euler, Model: Stable Diffusion XL"
    return encode(image, "JPEG", exif=data)


def _exif_only_camera() -> bytes:
    image = base_image(2, caption="13 expect: strict UNKNOWN / relaxed NO label")
    tags = {TAG_MAKE: "NIKON CORPORATION", TAG_MODEL: "NIKON Z 6"}
    return encode(image, "JPEG", exif=exif_for(image, tags))


def _png_itxt() -> bytes:
    from PIL.PngImagePlugin import PngInfo

    info = PngInfo()
    info.add_itxt("XML:com.adobe.xmp", xmp_packet("trainedAlgorithmicMedia").decode("utf-8"))
    return encode(base_image(4, caption="15 PNG expect: AI GENERATED"), "PNG", pnginfo=info)


def _png_raw_profile() -> bytes:
    from PIL.PngImagePlugin import PngInfo

    packet = xmp_packet("trainedAlgorithmicMedia")
    body = "\n" + "xmp" + "\n" + str(len(packet)) + "\n" + packet.hex()
    info = PngInfo()
    info.add_text("Raw profile type xmp", body)
    image = base_image(1, caption="17 PNG raw profile expect: AI GENERATED")
    return encode(image, "PNG", pnginfo=info)


def _contradiction() -> bytes:
    image = base_image(2, caption="18 expect: NO label (XMP wins)")
    return encode(
        image,
        "JPEG",
        xmp=xmp_packet("digitalCapture"),
        exif=exif_for(image, {TAG_SOFTWARE: "Midjourney v6.1"}),
    )


def _extended_xmp() -> bytes:
    jpeg = encode(base_image(3, caption="19 extended XMP expect: AI GENERATED"), "JPEG")
    packet = xmp_packet("trainedAlgorithmicMedia")
    filler = b"<pad>" + b"x" * 90_000 + b"</pad>"
    guid = b"A1B2C3D4E5F60718293A4B5C6D7E8F90"
    chunks = [filler[i : i + 60000] for i in range(0, len(filler), 60000)]

    segments = [XMP_SIG + packet]
    offset = 0
    for chunk in chunks:
        segments.append(
            XMP_EXT_SIG + guid + struct.pack(">I", len(filler)) + struct.pack(">I", offset) + chunk
        )
        offset += len(chunk)
    return splice_app1(jpeg, segments)


def _corrupt_xmp() -> bytes:
    jpeg = encode(base_image(4, caption="20 corrupt XMP expect: UNKNOWN"), "JPEG")
    truncated = b'<?xpacket begin=""?><x:xmpmeta><rdf:RDF><rdf:Desc'
    return splice_app1(jpeg, [XMP_SIG + truncated])


# -- The table ------------------------------------------------------------

CASES: list[Case] = [
    Case(
        file="01-iptc-ai-generated.jpg",
        description="IPTC trainedAlgorithmicMedia",
        strict="ai_generated",
        relaxed="ai_generated",
        build=lambda: iptc_jpeg(0, "trainedAlgorithmicMedia", "01 expect: AI GENERATED"),
    ),
    Case(
        file="02-iptc-ai-composite.jpg",
        description="IPTC compositeWithTrainedAlgorithmicMedia",
        strict="ai_composite",
        relaxed="ai_composite",
        build=lambda: iptc_jpeg(
            1, "compositeWithTrainedAlgorithmicMedia", "02 expect: AI composite"
        ),
    ),
    Case(
        file="03-iptc-ai-modified.jpg",
        description="IPTC algorithmicallyEnhanced",
        strict="ai_manipulated",
        relaxed="ai_manipulated",
        build=lambda: iptc_jpeg(2, "algorithmicallyEnhanced", "03 expect: AI MODIFIED"),
    ),
    Case(
        file="04-iptc-camera.jpg",
        description="IPTC digitalCapture - a real photograph",
        strict=None,
        relaxed=None,
        build=lambda: iptc_jpeg(3, "digitalCapture", "04 expect: NO label"),
        notes="A positive not-AI assertion. Must never be labelled, under either policy.",
    ),
    Case(
        file="05-iptc-digital-art.jpg",
        description="IPTC digitalArt - human-made digital work",
        strict=None,
        relaxed=None,
        build=lambda: iptc_jpeg(4, "digitalArt", "05 expect: NO label"),
    ),
    Case(
        file="06-iptc-composite-capture.jpg",
        description="IPTC compositeCapture - composite of real photos",
        strict=None,
        relaxed=None,
        build=lambda: iptc_jpeg(0, "compositeCapture", "06 expect: NO label"),
    ),
    Case(
        file="07-iptc-unrecognised-term.jpg",
        description="IPTC term this build does not know",
        strict="unknown",
        relaxed="unknown",
        build=lambda: iptc_jpeg(1, "quantumHolographicMedia", "07 expect: UNKNOWN"),
        notes="An unfamiliar term must read as unknown, never as a clean bill of health.",
    ),
    Case(
        file="08-iptc-bare-term.jpg",
        description="DigitalSourceType as a bare term, no CV URI",
        strict="ai_generated",
        relaxed="ai_generated",
        build=lambda: iptc_jpeg(
            2, "trainedAlgorithmicMedia", "08 expect: AI GENERATED", full_uri=False
        ),
    ),
    Case(
        file="09-exif-midjourney.jpg",
        description="EXIF Software names a known generator",
        strict="ai_generated",
        relaxed="ai_generated",
        build=_exif_midjourney,
        notes="LOW confidence: inferred from a tool name, not read from a provenance field.",
    ),
    Case(
        file="10-exif-photoshop-only.jpg",
        description="EXIF Software is an ordinary editor",
        strict="unknown",
        relaxed=None,
        build=_exif_photoshop,
        notes="PRECISION CHECK. Photoshop must not match: most images through it are not AI.",
    ),
    Case(
        file="11-exif-usercomment.jpg",
        description="Generation parameters in EXIF UserComment",
        strict="ai_generated",
        relaxed="ai_generated",
        build=_exif_user_comment,
        notes="UserComment lives in the Exif sub-IFD; IFD0 alone would miss it.",
    ),
    Case(
        file="12-no-metadata.jpg",
        description="No metadata of any kind",
        strict="unknown",
        relaxed=None,
        build=lambda: encode(
            base_image(1, caption="12 expect: strict UNKNOWN / relaxed NO label"), "JPEG"
        ),
        notes="The normal state of anything predating provenance metadata.",
    ),
    Case(
        file="13-exif-only-camera.jpg",
        description="EXIF camera tags only, no XMP",
        strict="unknown",
        relaxed=None,
        build=_exif_only_camera,
        notes=(
            "THE KEY ROW. EXIF carries no provenance field, so relaxed stays silent. "
            "Counting it would label essentially every camera photograph ever taken."
        ),
    ),
    Case(
        file="14-xmp-without-sourcetype.jpg",
        description="XMP present but no DigitalSourceType",
        strict="unknown",
        relaxed="unknown",
        build=lambda: encode(
            base_image(3, caption="14 expect: UNKNOWN under both policies"),
            "JPEG",
            xmp=xmp_packet(None, extra="<dc:creator>Test Suite</dc:creator>"),
        ),
        notes=(
            "A provenance-capable block that says nothing: where a stripped assertion shows up. "
            "Labelled under BOTH policies, unlike case 13."
        ),
    ),
    Case(
        file="15-png-iptc-ai.png",
        description="PNG carrying XMP in an iTXt chunk",
        strict="ai_generated",
        relaxed="ai_generated",
        build=_png_itxt,
    ),
    Case(
        file="16-webp-iptc-ai.webp",
        description="WebP carrying XMP",
        strict="ai_generated",
        relaxed="ai_generated",
        build=lambda: encode(
            base_image(0, caption="16 WebP expect: AI GENERATED"),
            "WEBP",
            xmp=xmp_packet("trainedAlgorithmicMedia"),
        ),
    ),
    Case(
        file="17-png-raw-profile-ai.png",
        description="PNG with ImageMagick hex-wrapped XMP",
        strict="ai_generated",
        relaxed="ai_generated",
        build=_png_raw_profile,
        notes="How metadata survives an ImageMagick step - common in editorial pipelines.",
    ),
    Case(
        file="18-contradiction.jpg",
        description="XMP says camera, EXIF says Midjourney",
        strict=None,
        relaxed=None,
        build=_contradiction,
        notes=(
            "The standardised HIGH-confidence assertion wins and short-circuits. Change "
            "this behaviour if you would rather surface the conflict."
        ),
    ),
    Case(
        file="19-extended-xmp-ai.jpg",
        description="Extended XMP split across APP1 segments",
        strict="ai_generated",
        relaxed="ai_generated",
        build=_extended_xmp,
        notes="Over ~64 KB, XMP must be split. Hand-built: Pillow refuses to write this.",
    ),
    Case(
        file="20-corrupt-xmp.jpg",
        description="Truncated, unparseable XMP packet",
        strict="unknown",
        relaxed="unknown",
        build=_corrupt_xmp,
        notes="Must not raise. A hostile file yields no claim, and the policy decides.",
    ),
    Case(
        file="21-small-thumbnail.jpg",
        description="AI image below the minimum label size",
        strict="ai_generated",
        relaxed="ai_generated",
        build=lambda: iptc_jpeg(0, "trainedAlgorithmicMedia", "21 small", size=(140, 80)),
        notes=(
            "DETECTION says ai_generated, but NO label is drawn: 80 px is under the 120 px floor. "
            "Verify by eye, not by the manifest."
        ),
    ),
    Case(
        file="22-panorama-ai.jpg",
        description="Very wide AI image",
        strict="ai_generated",
        relaxed="ai_generated",
        build=lambda: iptc_jpeg(
            1, "trainedAlgorithmicMedia", "22 panorama expect: AI GENERATED", size=(2000, 500)
        ),
        notes="Label size tracks the SHORTER edge, so it should not look tiny here.",
    ),
    Case(
        file="23-tall-portrait-ai.jpg",
        description="Very tall AI image",
        strict="ai_generated",
        relaxed="ai_generated",
        build=lambda: iptc_jpeg(
            2, "trainedAlgorithmicMedia", "23 portrait expect: AI GENERATED", size=(500, 1400)
        ),
    ),
    Case(
        file="24-dark-ai.jpg",
        description="Dark AI image",
        strict="ai_generated",
        relaxed="ai_generated",
        build=lambda: iptc_jpeg(
            3, "trainedAlgorithmicMedia", "24 dark expect: AI GENERATED", dark=True
        ),
        notes="For checking contrast, and for trying AI_LABEL_ICON_SET = 'eu-white'.",
    ),
]


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    manifest = []

    for entry in CASES:
        payload = entry.build()
        (OUT / entry.file).write_bytes(payload)

        with Image.open(io.BytesIO(payload)) as probe:
            size = probe.size

        manifest.append(entry.as_manifest_entry(payload, size))
        print(
            f"  {entry.file:<32} {size[0]:>5}x{size[1]:<5} {len(payload):>7} B   "
            f"strict={entry.strict!s:<13} relaxed={entry.relaxed}"
        )

    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"\nwrote {len(manifest)} images + manifest.json to {OUT}")


if __name__ == "__main__":
    main()
