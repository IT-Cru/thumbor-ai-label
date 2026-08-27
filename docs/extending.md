# Extending

## Writing a detector

Detectors are resolved from the `thumbor_ai_label.detectors` entry point group, so you can
ship one from your own package without touching this repository:

```toml
[project.entry-points."thumbor_ai_label.detectors"]
house_dam = "my_package.detectors:provenance"
```

Then select it in `thumbor.conf`:

```python
AI_LABEL_DETECTORS = ["iptc", "house_dam", "exif"]
```

## The contract

A detector is any module or object exposing `NAME`, `REQUIRES` and `detect`:

```python
from thumbor_ai_label.detect import Confidence, Detection, SourceType
from thumbor_ai_label.scan import SegmentKind

NAME = "house_dam"

#: Segment kinds this detector needs. It is skipped without being called when none
#: are present — there is no point asking an XMP detector about a file with no XMP.
#: Use an empty frozenset if you do not need the scan at all.
REQUIRES = frozenset({SegmentKind.XMP})


def detect(scanned):
    for packet in scanned.xmp:
        ...
    return None
```

`detect` returns a `Detection` or `None`. Returning `None` means "I have nothing to say",
which is different from "this is not AI" — only a `NOT_AI` verdict says that.

### Async is supported

`detect` may be a coroutine. The built-ins are pure CPU work over bytes already in memory,
but a detector that calls another system — a DAM lookup, an internal API — needs to await:

```python
async def detect(scanned):
    async with httpx.AsyncClient() as client:
        ...
```

The runner awaits the result if it is awaitable, so both forms work.

!!! warning "You are in the request path"
    A detector runs on every uncached image. A slow network call becomes a slow page. Use
    timeouts, and consider whether the answer can be cached upstream instead.

## What a Detection means

```python
Detection(
    source_type=SourceType.AI_GENERATED,
    confidence=Confidence.HIGH,
    detector=NAME,
    evidence="trainedAlgorithmicMedia",
    generator="Adobe Firefly",
)
```

**`confidence` is not a formality.** It decides ordering and short-circuiting:

- **HIGH** — an explicit standardised assertion. Stops the run; nothing after it is asked.
- **MEDIUM** — a structural signal whose meaning is clear but unverified.
- **LOW** — a heuristic that will produce false positives and must never be the sole basis
  for a strong claim. Never short-circuits.

Claim HIGH only if you are reading a field that *means* what you are asserting. A DAM
lookup against your own editorial records is a fair HIGH; a filename pattern is not.

**`evidence` is surfaced publicly** on the meta endpoint when `AI_LABEL_META_VERBOSE` is
on. Keep it short and free of anything you would not publish.

### `UNKNOWN` is not "not AI"

If you recognise the field but not the value, return `UNKNOWN`, never `NOT_AI`. An
unfamiliar value must not read as a clean bill of health — the fail-closed policy depends
on that distinction.

## Failure behaviour

A detector that raises is logged and ignored: it yields no claim rather than taking down
the request or suppressing the detectors behind it. You do not need defensive try/except
around your own logic for that reason alone — but you do need it if a partial result is
better than none.

## Where a detector belongs

Detectors covering a **public standard** belong in this repository — open an issue. A
lookup against your own internal system belongs in your own package, which is exactly what
the entry point group is for.
