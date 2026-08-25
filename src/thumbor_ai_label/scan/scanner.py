"""Entry point: sniff the container and dispatch to the right walker.

One walk per image. Each detector is later handed the segments it cares about,
so a file is never parsed twice no matter how many detectors are enabled.
"""

from __future__ import annotations

from . import jpeg, png, webp
from .types import DEFAULT_LIMITS, Container, ScanLimits, ScanResult

Buffer = bytes | bytearray | memoryview


def sniff(view: memoryview) -> Container | None:
    if len(view) >= 3 and view[:3] == jpeg.MAGIC:
        return Container.JPEG
    if len(view) >= 8 and view[:8] == png.MAGIC:
        return Container.PNG
    if len(view) >= 12 and view[:4] == webp.MAGIC and view[8:12] == webp.FORM:
        return Container.WEBP
    return None


def scan(data: Buffer, limits: ScanLimits = DEFAULT_LIMITS) -> ScanResult:
    """Extract metadata payloads from an image buffer.

    Never raises on malformed input: a corrupt or hostile file yields a partial
    result with ``truncated`` set and an explanatory note. A scan runs inside the
    request path, so failing loudly here would turn a weird image into a 500.
    """
    view = memoryview(data)
    if view.format != "B" or view.ndim != 1:
        view = view.cast("B")

    result = ScanResult()
    container = sniff(view)
    result.container = container

    if container is None:
        result.note("unrecognised container")
        return result

    try:
        if container is Container.JPEG:
            jpeg.scan_jpeg(view, result, limits)
        elif container is Container.PNG:
            png.scan_png(view, result, limits)
        else:
            webp.scan_webp(view, result, limits)
    except Exception as exc:  # noqa: BLE001
        # Defensive: the walkers are bounds-checked, but this runs on untrusted bytes
        # in a request path and must not propagate.
        result.note(f"scan aborted: {type(exc).__name__}: {exc}")
        result.truncated = True

    return result
