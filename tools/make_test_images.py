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


# Each case: (filename, builder, description, expected-strict, expected-relaxed)
# Expected values are the `label` state, or None for "no label drawn".
CASES = []


def case(name, description, strict, relaxed, notes=""):
    def register(builder):
        CASES.append(
            {
                "file": name,
                "description": description,
                "expected": {"strict": strict, "relaxed": relaxed},
                "notes": notes,
                "builder": builder,
            }
        )
        return builder

    return register


def iptc_jpeg(index, term, caption, full_uri=True, size=(800, 600), dark=False):
    image = base_image(index, size=size, dark=dark, caption=caption)
    return encode(image, "JPEG", xmp=xmp_packet(term, full_uri=full_uri))


# -- A. IPTC DigitalSourceType, the primary signal ------------------------

case("01-iptc-ai-generated.jpg", "IPTC trainedAlgorithmicMedia", "ai_generated", "ai_generated")(
    lambda: iptc_jpeg(0, "trainedAlgorithmicMedia", "01 expect: AI GENERATED")
)
case("02-iptc-ai-composite.jpg", "IPTC compositeWithTrainedAlgorithmicMedia",
     "ai_composite", "ai_composite")(
    lambda: iptc_jpeg(1, "compositeWithTrainedAlgorithmicMedia", "02 expect: AI composite")
)
case("03-iptc-ai-modified.jpg", "IPTC algorithmicallyEnhanced", "ai_manipulated", "ai_manipulated")(
    lambda: iptc_jpeg(2, "algorithmicallyEnhanced", "03 expect: AI MODIFIED")
)
case("04-iptc-camera.jpg", "IPTC digitalCapture - a real photograph", None, None,
     "A positive not-AI assertion. Must never be labelled, under either policy.")(
    lambda: iptc_jpeg(3, "digitalCapture", "04 expect: NO label")
)
case("05-iptc-digital-art.jpg", "IPTC digitalArt - human-made digital work", None, None)(
    lambda: iptc_jpeg(4, "digitalArt", "05 expect: NO label")
)
case("06-iptc-composite-capture.jpg", "IPTC compositeCapture - composite of real photos",
     None, None)(
    lambda: iptc_jpeg(0, "compositeCapture", "06 expect: NO label")
)
case("07-iptc-unrecognised-term.jpg", "IPTC term this build does not know", "unknown", "unknown",
     "An unfamiliar term must read as unknown, never as a clean bill of health.")(
    lambda: iptc_jpeg(1, "quantumHolographicMedia", "07 expect: UNKNOWN")
)
case("08-iptc-bare-term.jpg", "DigitalSourceType as a bare term, no CV URI",
     "ai_generated", "ai_generated")(
    lambda: iptc_jpeg(2, "trainedAlgorithmicMedia", "08 expect: AI GENERATED", full_uri=False)
)

# -- B. EXIF vendor hints, the weak fallback ------------------------------

@case("09-exif-midjourney.jpg", "EXIF Software names a known generator",
      "ai_generated", "ai_generated",
      "LOW confidence: inferred from a tool name, not read from a provenance field.")
def _():
    image = base_image(3, caption="09 expect: AI GENERATED (low conf)")
    return encode(image, "JPEG", exif=exif_for(image, {TAG_SOFTWARE: "Midjourney v6.1"}))


@case("10-exif-photoshop-only.jpg", "EXIF Software is an ordinary editor", "unknown", None,
      "PRECISION CHECK. Photoshop must not match: most images through it are not AI.")
def _():
    image = base_image(4, caption="10 expect: strict UNKNOWN / relaxed NO label")
    return encode(image, "JPEG", exif=exif_for(image, {TAG_SOFTWARE: "Adobe Photoshop 25.0"}))


@case("11-exif-usercomment.jpg", "Generation parameters in EXIF UserComment",
      "ai_generated", "ai_generated",
      "UserComment lives in the Exif sub-IFD; IFD0 alone would miss it.")
def _():
    image = base_image(0, caption="11 expect: AI GENERATED (low conf)")
    data = image.getexif()
    data[TAG_MAKE] = "TestCorp"
    sub = data.get_ifd(0x8769)
    sub[0x9286] = b"ASCII\x00\x00\x00Steps: 20, Sampler: Euler, Model: Stable Diffusion XL"
    return encode(image, "JPEG", exif=data)


# -- C. Where the two policies diverge ------------------------------------

case("12-no-metadata.jpg", "No metadata of any kind", "unknown", None,
     "The normal state of a pre-2023 archive.")(
    lambda: encode(base_image(1, caption="12 expect: strict UNKNOWN / relaxed NO label"), "JPEG")
)


@case("13-exif-only-camera.jpg", "EXIF camera tags only, no XMP", "unknown", None,
      "THE KEY ROW. EXIF carries no provenance field, so relaxed stays silent. "
      "Counting it would label essentially every camera photograph ever taken.")
def _():
    image = base_image(2, caption="13 expect: strict UNKNOWN / relaxed NO label")
    return encode(image, "JPEG", exif=exif_for(
        image, {TAG_MAKE: "NIKON CORPORATION", TAG_MODEL: "NIKON Z 6"}
    ))


case("14-xmp-without-sourcetype.jpg", "XMP present but no DigitalSourceType", "unknown", "unknown",
     "A provenance-capable block that says nothing: where a stripped assertion shows up. "
     "Labelled under BOTH policies, unlike case 13.")(
    lambda: encode(
        base_image(3, caption="14 expect: UNKNOWN under both policies"),
        "JPEG",
        xmp=xmp_packet(None, extra="<dc:creator>Test Suite</dc:creator>"),
    )
)

# -- D. Container coverage ------------------------------------------------

@case("15-png-iptc-ai.png", "PNG carrying XMP in an iTXt chunk", "ai_generated", "ai_generated")
def _():
    from PIL.PngImagePlugin import PngInfo

    info = PngInfo()
    info.add_itxt("XML:com.adobe.xmp", xmp_packet("trainedAlgorithmicMedia").decode("utf-8"))
    return encode(base_image(4, caption="15 PNG expect: AI GENERATED"), "PNG", pnginfo=info)


case("16-webp-iptc-ai.webp", "WebP carrying XMP", "ai_generated", "ai_generated")(
    lambda: encode(
        base_image(0, caption="16 WebP expect: AI GENERATED"),
        "WEBP",
        xmp=xmp_packet("trainedAlgorithmicMedia"),
    )
)


@case("17-png-raw-profile-ai.png", "PNG with ImageMagick hex-wrapped XMP",
      "ai_generated", "ai_generated",
      "How metadata survives an ImageMagick step - common in editorial pipelines.")
def _():
    from PIL.PngImagePlugin import PngInfo

    packet = xmp_packet("trainedAlgorithmicMedia")
    body = "\n" + "xmp" + "\n" + str(len(packet)) + "\n" + packet.hex()
    info = PngInfo()
    info.add_text("Raw profile type xmp", body)
    image = base_image(1, caption="17 PNG raw profile expect: AI GENERATED")
    return encode(image, "PNG", pnginfo=info)


# -- E. Edge cases --------------------------------------------------------

@case("18-contradiction.jpg", "XMP says camera, EXIF says Midjourney", None, None,
      "The standardised HIGH-confidence assertion wins and short-circuits. Change this "
      "behaviour if you would rather surface the conflict.")
def _():
    image = base_image(2, caption="18 expect: NO label (XMP wins)")
    return encode(
        image, "JPEG",
        xmp=xmp_packet("digitalCapture"),
        exif=exif_for(image, {TAG_SOFTWARE: "Midjourney v6.1"}),
    )


@case("19-extended-xmp-ai.jpg", "Extended XMP split across APP1 segments",
      "ai_generated", "ai_generated",
      "Over ~64 KB, XMP must be split. Hand-built: Pillow refuses to write this.")
def _():
    jpeg = encode(base_image(3, caption="19 extended XMP expect: AI GENERATED"), "JPEG")
    packet = xmp_packet("trainedAlgorithmicMedia")
    filler = b"<pad>" + b"x" * 90_000 + b"</pad>"
    guid = b"A1B2C3D4E5F60718293A4B5C6D7E8F90"
    chunks = [filler[i:i + 60000] for i in range(0, len(filler), 60000)]
    segments = [XMP_SIG + packet]
    offset = 0
    for chunk in chunks:
        segments.append(
            XMP_EXT_SIG + guid + struct.pack(">I", len(filler)) + struct.pack(">I", offset) + chunk
        )
        offset += len(chunk)
    return splice_app1(jpeg, segments)


@case("20-corrupt-xmp.jpg", "Truncated, unparseable XMP packet", "unknown", "unknown",
      "Must not raise. A hostile file yields no claim, and the policy decides.")
def _():
    jpeg = encode(base_image(4, caption="20 corrupt XMP expect: UNKNOWN"), "JPEG")
    return splice_app1(jpeg, [XMP_SIG + b'<?xpacket begin=""?><x:xmpmeta><rdf:RDF><rdf:Desc'])


case("21-small-thumbnail.jpg", "AI image below the minimum label size",
     "ai_generated", "ai_generated",
     "DETECTION says ai_generated, but NO label is drawn: 80 px is under the 120 px floor. "
     "Verify by eye, not by the manifest.")(
    lambda: iptc_jpeg(0, "trainedAlgorithmicMedia", "21 small", size=(140, 80))
)
case("22-panorama-ai.jpg", "Very wide AI image", "ai_generated", "ai_generated",
     "Label size tracks the SHORTER edge, so it should not look tiny here.")(
    lambda: iptc_jpeg(
        1, "trainedAlgorithmicMedia", "22 panorama expect: AI GENERATED", size=(2000, 500)
    )
)
case("23-tall-portrait-ai.jpg", "Very tall AI image", "ai_generated", "ai_generated")(
    lambda: iptc_jpeg(
        2, "trainedAlgorithmicMedia", "23 portrait expect: AI GENERATED", size=(500, 1400)
    )
)
case("24-dark-ai.jpg", "Dark AI image", "ai_generated", "ai_generated",
     "For checking contrast, and for trying AI_LABEL_ICON_SET = 'eu-white'.")(
    lambda: iptc_jpeg(3, "trainedAlgorithmicMedia", "24 dark expect: AI GENERATED", dark=True)
)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    manifest = []

    for entry in CASES:
        payload = entry["builder"]()
        path = OUT / entry["file"]
        path.write_bytes(payload)

        with Image.open(io.BytesIO(payload)) as probe:
            dimensions = probe.size

        manifest.append(
            {
                "file": entry["file"],
                "description": entry["description"],
                "size": list(dimensions),
                "bytes": len(payload),
                "expected": entry["expected"],
                "notes": entry["notes"],
            }
        )
        print(
            "  {:<32} {:>5}x{:<5} {:>7} B   strict={:<13} relaxed={}".format(
                entry["file"], dimensions[0], dimensions[1], len(payload),
                str(entry["expected"]["strict"]), str(entry["expected"]["relaxed"]),
            )
        )

    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"\nwrote {len(manifest)} images + manifest.json to {OUT}")


if __name__ == "__main__":
    main()
