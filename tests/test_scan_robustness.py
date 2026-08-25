"""The scanner runs on untrusted bytes inside a request path.

Two properties matter more than any single parse result: it must never raise, and
its cost must not scale with image size. Everything here guards one of those.
"""

from __future__ import annotations

import random
import time

import pytest

from thumbor_ai_label.scan import Container, ScanResult, scan

from .builders import (
    app1_exif,
    app1_xmp,
    app11_jumbf,
    build_jpeg,
    build_png,
    build_webp,
    itxt,
    png_chunk,
    riff_chunk,
)

XMP = b'<x:xmpmeta xmlns:x="adobe:ns:meta/"/>'
TIFF = b"II*\x00\x08\x00\x00\x00" + b"\x00" * 8

SAMPLES = {
    "jpeg": build_jpeg([app1_exif(TIFF), app1_xmp(XMP), app11_jumbf(b"manifest")]),
    "png": build_png([itxt(b"XML:com.adobe.xmp", XMP), png_chunk(b"eXIf", TIFF)]),
    "webp": build_webp([riff_chunk(b"XMP ", XMP), riff_chunk(b"EXIF", TIFF)]),
}


@pytest.mark.parametrize("name", sorted(SAMPLES))
def test_truncation_at_every_offset_never_raises(name):
    raw = SAMPLES[name]
    for cut in range(len(raw) + 1):
        result = scan(raw[:cut])
        assert isinstance(result, ScanResult)


@pytest.mark.parametrize("name", sorted(SAMPLES))
def test_single_byte_corruption_never_raises(name):
    raw = bytearray(SAMPLES[name])
    rng = random.Random(20260824)
    for _ in range(2000):
        mutated = bytearray(raw)
        index = rng.randrange(len(mutated))
        mutated[index] = rng.randrange(256)
        result = scan(bytes(mutated))
        assert isinstance(result, ScanResult)


@pytest.mark.parametrize("name", sorted(SAMPLES))
def test_burst_corruption_never_raises(name):
    raw = SAMPLES[name]
    rng = random.Random(99)
    for _ in range(500):
        mutated = bytearray(raw)
        start = rng.randrange(len(mutated))
        for offset in range(start, min(start + rng.randrange(1, 32), len(mutated))):
            mutated[offset] = rng.randrange(256)
        assert isinstance(scan(bytes(mutated)), ScanResult)


def test_random_buffers_never_raise():
    rng = random.Random(7)
    prefixes = [b"\xff\xd8\xff", b"\x89PNG\r\n\x1a\n", b"RIFF\x00\x00\x00\x00WEBP", b""]
    for _ in range(1500):
        prefix = prefixes[rng.randrange(len(prefixes))]
        body = bytes(rng.randrange(256) for _ in range(rng.randrange(0, 200)))
        assert isinstance(scan(prefix + body), ScanResult)


@pytest.mark.parametrize("raw", [b"", b"\x00", b"\xff", b"\xff\xd8", b"\xff\xd8\xff", b"RIFF"])
def test_degenerate_buffers(raw):
    result = scan(raw)
    assert isinstance(result, ScanResult)
    assert result.segments == []


def test_accepts_every_buffer_type():
    raw = SAMPLES["jpeg"]
    for buffer in (raw, bytearray(raw), memoryview(raw)):
        assert scan(buffer).xmp == [XMP]


def test_cost_does_not_scale_with_image_size():
    """Guards the performance contract: the walk stops at the metadata, not the end.

    A regression that made the scanner read entrails would blow this bound by
    orders of magnitude.
    """
    header = b"\xff\xd8" + app1_xmp(XMP)
    huge = header + b"\xff\xda\x00\x0c" + b"\x00" * 10 + bytes(64 * 1024 * 1024) + b"\xff\xd9"

    start = time.perf_counter()
    result = scan(huge)
    elapsed = time.perf_counter() - start

    assert result.xmp == [XMP]
    assert elapsed < 0.1, f"scanning 64 MB took {elapsed:.3f}s; the walk is reading image data"


def test_a_hostile_file_still_reports_that_metadata_exists():
    """The fail-closed policy keys off has_any_metadata, so it must survive damage."""
    raw = bytearray(SAMPLES["jpeg"])
    raw[-20:] = b"\x00" * 20  # wreck the tail, leave the metadata segments intact
    result = scan(bytes(raw))
    assert result.has_any_metadata is True
    assert result.container is Container.JPEG


def test_an_unexpected_walker_error_is_contained(monkeypatch):
    """The last-resort backstop: a bug in a walker must not become a 500."""
    from thumbor_ai_label.scan import scanner

    def explode(*_args, **_kwargs):
        raise RuntimeError("walker bug")

    monkeypatch.setattr(scanner.jpeg, "scan_jpeg", explode)
    result = scan(SAMPLES["jpeg"])
    assert result.truncated is True
    assert any("RuntimeError" in note for note in result.notes)


def test_segment_repr_does_not_leak_the_payload():
    """Payloads carry GPS, creator and caption data; they must stay out of logs."""
    secret = b"<xmp>creator: a real person, gps: 48.1,11.5</xmp>"
    result = scan(build_jpeg([app1_xmp(secret)]))
    text = repr(result.segments[0])
    assert b"real person" not in text.encode()
    assert f"bytes={len(secret)}" in text


def test_webp_walker_rejects_a_non_webp_riff_when_called_directly():
    from thumbor_ai_label.scan import webp as webp_module
    from thumbor_ai_label.scan.types import DEFAULT_LIMITS

    result = ScanResult()
    webp_module.scan_webp(memoryview(b"RIFF\x04\x00\x00\x00WAVE"), result, DEFAULT_LIMITS)
    assert result.truncated is True
    assert result.segments == []
