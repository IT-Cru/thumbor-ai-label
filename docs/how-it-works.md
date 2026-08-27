# How it works

Internals, for people changing the code. Nothing here is needed to run the plugin.

## The request path

| Stage | Where | What happens |
|---|---|---|
| Load | `engine.load()` | Scan the original bytes, park the result on the request |
| Detect | filter, post-transform | Run detectors against the scan (async) |
| Decide | `policy.decide()` | Turn findings into a label state, or none |
| Draw | `compose.apply_label()` | Size, place and composite the icon |
| Publish | `meta.inject()` | Merge the verdict into a `/meta/` response |

### Why the engine, and not a filter

`BaseEngine.load(buffer, extension)` is **the only point in Thumbor's flow that always
sees the original file**. Both fetch paths converge on it: a storage hit loads the cached
original, a storage miss loads what the loader returned. Hooking there needs no assumptions
about which loader or storage backend is configured.

The alternatives do not work:

- A `PHASE_AFTER_LOAD` filter cannot reach the buffer — it is a local in `get_image()`,
  never stored on the context.
- Overriding `_fetch` only sees the buffer on storage hits; the miss path nulls it before
  returning.
- The PIL engine retains `self.exif` from `img.info` but never XMP, so engine state is no
  substitute.

`load()` is **synchronous**, so only the scan runs there. Detectors run in the filter,
which is async and can therefore accommodate one that calls out to another system.

The scan *result* is parked on the request, not the buffer, so nothing keeps a decoded
original alive for the length of the request.

### Why verdicts cannot leak between images

Thumbor builds a fresh `Context` per request in `ContextHandler.initialize`, and the engine
is constructed per context. Attributes parked on the context cannot cross requests.

The verdict is **memoised**, because `BaseFilter.run()` iterates frame engines — a filter
fires once per frame on an animated image, and detection should not repeat for every frame
of a GIF. The *draw* guard is set on the engine rather than the request, so each frame is
still labelled exactly once.

## The container scanner

`thumbor_ai_label.scan` lifts XMP, EXIF and JUMBF payloads out of a buffer. It has **no
Thumbor import**, so it can be tested and reused independently of Thumbor's dependency
pins.

```python
from thumbor_ai_label.scan import scan

result = scan(buffer)          # bytes, bytearray or memoryview
result.container               # Container.JPEG | PNG | WEBP | None
result.xmp                     # list[bytes] — XMP packets
result.exif                    # list[bytes] — starting at the TIFF header
result.jumbf                   # list[bytes] — reassembled JUMBF boxes
result.has_any_metadata        # what the fail-closed policy keys off
result.truncated, result.notes # how far the walk got, and why it stopped
```

### Performance

The walk **never decodes a pixel**. JPEG stops at the first scan header; PNG and WebP skip
image data by length arithmetic.

| Case | File | Median scan |
|---|---|---|
| 640×480 JPEG, XMP + EXIF | 0.1 MB | 4.9 µs |
| 2000×1500 JPEG, XMP + EXIF | 1.5 MB | 4.9 µs |
| 4000×3000 JPEG, XMP + EXIF | 6.5 MB | 4.9 µs |
| 4000×3000 WebP, XMP + EXIF | 7.0 MB | 3.6 µs |

**A 65× range in file size, no measurable change in scan time.** That flatness is the
claim; the absolute microseconds are machine-specific. `tools/bench_scan.py` reproduces the
table, and a test asserts the flatness — so a regression that starts reading image data
fails the suite rather than quietly slowing things down.

### Cases beyond the obvious

- **Adobe Extended XMP** — reassembled across APP1 segments by offset. A gap yields the
  contiguous prefix plus a note, rather than spliced-together invalid XML.
- **Multi-packet JUMBF** — APP11 packets reassembled per box instance, in sequence order.
- **ImageMagick raw profiles** — hex-wrapped XMP/EXIF in PNG `tEXt`/`zTXt`/`iTXt`, common
  in pipelines that have passed through ImageMagick.
- **PNG metadata after IDAT** — legal, so the walk continues to IEND.
- **Bad PNG CRCs** — not a reason to discard a payload every other tool reads.

### Safety

The scanner runs on untrusted bytes inside a request path, so it **never raises**. A
corrupt or hostile file yields a partial result with `truncated` set and a note explaining
why — an exception here would turn a weird image into a 500.

Byte budgets bound XMP, EXIF and JUMBF independently; zlib inflation is capped against
compression bombs; oversized Extended XMP is refused from its declared length before
anything is allocated. `RawSegment.__repr__` omits payloads, which can carry GPS and
creator data, so they stay out of logs and tracebacks.

The suite fuzzes roughly 10,500 mutated and truncated inputs across all three containers,
asserting no exception escapes.

## Detectors

### States

`NOT_AI` and `UNKNOWN` are **deliberately distinct**. `NOT_AI` is a positive assertion —
something in the file says a camera took this. `UNKNOWN` is the absence of any such claim.
The fail-closed policy treats them very differently, so collapsing them would quietly
defeat it.

### Execution

Detectors run in configured order. One whose required segment kinds are absent is skipped
without being called. The run stops at the first HIGH-confidence verdict; a LOW-confidence
one never short-circuits, so a heuristic cannot pre-empt the standard. A detector that
raises is logged and ignored — it yields no claim rather than taking down the request or
suppressing the detectors behind it.

### Why `iptc` uses no XML parser

The input is attacker-controllable, and an XML parser on untrusted input invites
entity-expansion and external-entity attacks. Hardening one costs more than the targeted
scan, which is also faster. A test asserts a billion-laughs payload is inert.

The namespace **prefix is discovered** from the packet rather than assumed: `Iptc4xmpExt`
is conventional, but prefixes are arbitrary in XML, so the packet is asked which prefix it
bound to the IPTC extension namespace. UTF-8, UTF-16 and UTF-32 packets are all handled.

### Why `exif` is LOW confidence

EXIF defines no provenance field, so the verdict is inferred from a tool name rather than
read from a field that means what we need it to mean. Only IFD0 and the Exif sub-IFD are
walked, through a bounded parser with no dependency, which never raises on malformed input.

`UserComment` lives in the sub-IFD, which is why IFD0 alone would miss it. Its field type
is accepted as either `UNDEFINED` (what the specification says) or `BYTE` (what Pillow
writes) — both appear in real files, and accepting only the conformant one silently skipped
half the encoders in the world. That bug survived 340 passing tests and was found by the
first piece of real encoder output.

## Sizing and placement

Label size tracks the **shorter** edge, so it carries the same visual weight on a panorama
as on a square crop. Scaling by width alone makes labels on wide images look tiny and on
tall ones absurd.

**Labels are not assumed to be square.** The official EU marks are icon-plus-text lockups
around 3:1, so `AI_LABEL_SIZE_RATIO`, `MIN_SIZE` and `MAX_SIZE` describe *height*, and
width follows the icon's aspect ratio. A wide mark on a narrow crop is scaled down to fit
rather than squashed — deforming an official mark would be worse than shrinking it.

Palette and greyscale images are promoted to RGB before compositing: an antialiased label
cannot be composited into a palette, and quietly drawing an aliased one instead would look
broken.

### When labelling fails

Labelling never takes image delivery down — a bad icon path would otherwise turn every
request into a 500. Failures are logged at error level. `AI_LABEL_STRICT_ERRORS = True`
makes them fatal instead, for deployments that would rather serve nothing than serve an
unlabelled image.

That flag is read off **raw config**, not through resolved settings. Settings resolution is
itself a thing that can fail — a bad icon path is the obvious case — and reading the flag
through it would mean broken icon config silently disabled the very setting meant to make
broken config fatal.

## Always-on

Thumbor has no native "always run this filter" hook, so the plugin supplies one by wrapping
the per-request filters factory. `Context.filters_factory` is built per request, so the
wrapper is installed in the handler's `initialize` and cannot leak between requests. No
Thumbor handler code is copied, so there is little to break on a Thumbor upgrade.

**The label is appended last, deliberately.** It is drawn after every other post-transform
filter, so a URL cannot blur, desaturate or overlay it away. A test pins this by requesting
`filters:blur(12)` and asserting the label survives.

An explicit `ai_label()` in a URL works alongside always-on and does not double draw.

### Boot-time validation

`APP_CLASS` resolves all settings at startup, so a typo'd icon path, an unknown detector
name or an invalid enum surfaces when Thumbor starts rather than as images quietly going
out unlabelled. It logs and continues by default; `AI_LABEL_STRICT_ERRORS` makes it refuse
to start.

Startup also logs when labelling is effectively off — `AI_LABEL_ENABLED = False`, or an
empty detector list — because "no labels" and "no AI images" look identical from outside.

## How the meta endpoint is wired

`JSONEngine.read()` builds the meta response and offers no hook, so the handler wraps
`_load_results` and the verdict is merged into the serialised payload — a **JSON round-trip
rather than a string splice**, so a change to Thumbor's own payload cannot corrupt it.
JSONP via `META_CALLBACK_NAME` is unwrapped and rewrapped.

`_load_results` runs in **Thumbor's thread pool**, off the event loop, so nothing there can
await. The verdict is read from where the label filter already stored it, and
`after_transform` guarantees it exists first.

Injection failure returns the original response untouched: a broken labelling feature must
not break an endpoint clients rely on.

Drawing is skipped entirely on meta requests — the response is JSON, and the engine at that
point is Thumbor's `JSONEngine` wrapping the real one.
