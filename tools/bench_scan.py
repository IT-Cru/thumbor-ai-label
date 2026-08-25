"""Measure scan cost against realistic image sizes.

The claim under test: scan time is a function of how much metadata a file carries,
not how large the image is.
"""

from __future__ import annotations

import io
import statistics
import time

from PIL import Image

from thumbor_ai_label.scan import scan

XMP = (
    b'<?xpacket begin="\xef\xbb\xbf"?><x:xmpmeta xmlns:x="adobe:ns:meta/">'
    b'<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
    b'<rdf:Description xmlns:Iptc4xmpExt="http://iptc.org/std/Iptc4xmpExt/2008-02-29/" '
    b'Iptc4xmpExt:DigitalSourceType='
    b'"http://cv.iptc.org/newscodes/digitalsourcetype/trainedAlgorithmicMedia"/>'
    b'</rdf:RDF></x:xmpmeta><?xpacket end="w"?>'
)

RUNS = 200


def make(size, fmt="JPEG", **kwargs):
    image = Image.new("RGB", size)
    # Noise keeps the encoder from producing an unrealistically compressible file.
    pixels = size[0] * size[1]
    image.putdata([((x * 7) % 256, (x * 13) % 256, (x * 29) % 256) for x in range(pixels)])
    buf = io.BytesIO()
    image.save(buf, fmt, **kwargs)
    return buf.getvalue()


def measure(raw):
    timings = []
    for _ in range(RUNS):
        start = time.perf_counter()
        scan(raw)
        timings.append((time.perf_counter() - start) * 1_000_000)
    return statistics.median(timings), max(timings)


def main():
    exif = Image.new("RGB", (1, 1)).getexif()
    exif[0x0131] = "Adobe Firefly"

    cases = [
        ("640x480   no metadata", make((640, 480))),
        ("640x480   xmp + exif", make((640, 480), xmp=XMP, exif=exif)),
        ("2000x1500 xmp + exif", make((2000, 1500), xmp=XMP, exif=exif)),
        ("4000x3000 xmp + exif", make((4000, 3000), xmp=XMP, exif=exif)),
        ("4000x3000 PNG xmp", make((4000, 3000), "PNG")),
        ("4000x3000 WEBP xmp", make((4000, 3000), "WEBP", xmp=XMP, exif=exif)),
    ]

    print("{:<26} {:>10} {:>12} {:>12}".format("case", "file", "median", "worst"))
    print("-" * 62)
    for label, raw in cases:
        median, worst = measure(raw)
        print(
            f"{label:<26} {len(raw) / 1_000_000:>9.1f}M {median:>10.1f}us {worst:>10.1f}us"
        )


if __name__ == "__main__":
    main()
