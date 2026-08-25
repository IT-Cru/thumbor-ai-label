# thumbor-ai-label

A Thumbor plugin. It reads AI provenance metadata from the source image and
composites an AI label as a watermark layer on every generated image style.

> **Status: feature-complete for the read-and-label scope.** Scanning, detection,
> policy, icons, compositing, the filter, always-on wiring and the meta endpoint all
> work end to end, verified over real HTTP requests through Thumbor's own app.

## Why this exists — EU AI Act Article 50

**Article 50 has applied since 2 August 2026.** Non-compliance carries fines of up to
€15 million or 3% of worldwide annual turnover.

This plugin targets **Article 50(4)**, the *deployer* obligation: anyone publishing a
deep fake — AI-generated or manipulated image content that would falsely appear
authentic — must disclose that the content has been artificially generated or
manipulated. Article 50(5) requires that disclosure be made "in a clear and
distinguishable manner at the latest at the time of the first interaction or
exposure."

A publisher is a **deployer**, not a provider. That distinction decides what you owe:

| | Article 50(2) — providers | Article 50(4) — deployers |
|---|---|---|
| Who | Whoever builds/ships the AI system | Whoever publishes the output |
| What | **Machine-readable** marking | **Human-perceptible** disclosure |
| Applies to a publisher? | Usually no | **Yes** |

The Commission is explicit that deployers **cannot rely solely on machine-readable
markings embedded by providers** — human-perceptible disclosure is required at first
exposure. The Code of Practice on Transparency of AI-Generated Content (published
10 June 2026) asks for a **"clearly visible, fixed icon"** on images, directly
embedded.

A burnt-in label on every derivative is precisely that: visible, fixed, embedded,
present at first exposure, and — because the label is composited after every other
filter — not removable through URL manipulation.

### What this plugin covers, and what it does not

| Requirement | Status |
|---|---|
| Visible, human-perceptible label | ✅ Burnt into every derivative |
| Directly embedded in the image | ✅ Not a CSS overlay a client can drop |
| Present at first exposure | ✅ Every style carries it |
| Survives downstream filtering | ✅ Composited last; `blur()` cannot erase it |
| Distinguishes generated from modified | ✅ Separate states and icons |
| Official EU icon set | ✅ Bundled — `AI_LABEL_ICON_SET = "eu"` |
| Icon paired with a text label | ✅ The EU labels read "AI GENERATED" / "AI MODIFIED" |
| Alt text / ARIA for assistive tech | ⚠️ Verdict published on `/meta/`; your CMS must use it |
| Deciding *which* images are AI | ⚠️ Only detects what metadata declares |
| Deep-fake scope and creative exemption | ⚠️ Over-labels — see below |

### The official EU icons are bundled

The Commission published a harmonised icon set on 10 June 2026, free to use without
attribution. **Their use is optional; the disclosure obligation is not.** They ship
with this plugin:

```python
AI_LABEL_ICON_SET = "eu"  # dark labels, for light imagery
AI_LABEL_ICON_SET = "eu-white"  # light labels, for dark imagery
```

| Official mark | Plugin state |
|---|---|
| AI GENERATED | `ai_generated` |
| AI MODIFIED | `ai_manipulated`, `ai_composite` |
| *(none — see below)* | `unknown` |

`ai_composite` maps to **AI MODIFIED** because a composite containing AI elements is
exactly "pre-existing human-made content partially modified with AI".

**`unknown` never draws an official EU mark.** Those marks assert that content *is*
AI-generated. Using one on an image whose provenance merely could not be established
would make a claim the evidence does not support, so that state keeps this plugin's own
neutral icon. It looks visibly different from the official labels, and that is the
point.

The bundled files are the official artwork, proportionally downscaled to 256 px tall
and otherwise unaltered. `tools/fetch_eu_icons.py` rebuilds them from the Commission's
archive, so their provenance stays checkable.

> **Caveat worth reading.** The Commission notes that use of these icons by
> non-signatories of the Code of Practice "should not be construed as signaling of
> their adherence to the code", and that signatories must use them in accordance with
> its placement specifications. Decide with your counsel whether you are signing.

Source: <https://digital-strategy.ec.europa.eu/en/policies/eu-icons-labelling-ai-generated-content>

### Two honest limitations

**The `unknown` label has no legal basis.** Article 50 obliges you to disclose content
you know to be AI-generated. It does not ask you to mark content whose provenance you
cannot establish. Under the default `strict` policy this plugin labels every image
without a positive not-AI assertion — which on a legacy archive is most of them, and
means putting an AI-adjacent mark on genuine photographs. That is a defensive posture,
not a legal requirement, and it may mislead readers in its own way. Consider
`AI_LABEL_POLICY = "relaxed"`.

**Accessibility needs your CMS to cooperate.** Article 50(5) requires disclosure to meet
accessibility requirements, and the Commission asks implementers to expose the label
through alt text or ARIA. A label burnt into pixels is invisible to a screen reader,
and Thumbor serves images — it does not control the surrounding HTML.

The plugin closes its half: the verdict is published on Thumbor's `/meta/` endpoint (see
below). Your CMS has to read it and write the alt text or ARIA label. Nothing this
plugin can do will make a burnt-in label reach a screen reader on its own.

### Scope: this plugin over-labels

Article 50(4) covers **deep fakes** — content that "would falsely appear to a person to
be authentic" — and exempts evidently creative, satirical or artistic work. This plugin
cannot judge realism or artistic intent, so it labels every image whose metadata
declares AI involvement. Over-disclosure is the safer direction legally, but it has an
editorial cost you should weigh.

Equally, the plugin only sees what the metadata says. An AI image that arrives with its
provenance stripped passes through unlabelled. The Code of Practice expects deployers to
run "clear and consistent internal processes" combining automated detection with human
oversight — this plugin is the automated half, not the whole obligation.

> This section is a technical mapping of the plugin's behaviour onto published
> requirements and guidance. It is not legal advice. Have your own counsel confirm
> what Article 50 requires of your organisation.


## Install

```bash
pip install thumbor-ai-label
```

The plugin is **read-only**. It reads metadata to decide which label to draw and
never writes anything back into an image.

Then in `thumbor.conf`:

```python
# Labels every image, with no change to any URL.
APP_CLASS = "thumbor_ai_label.app.AiLabelServiceApp"

# The engine hook is what sees the original bytes; without it nothing is detected.
ENGINE = "thumbor_ai_label.engine"

AI_LABEL_DETECTORS = ["iptc", "exif"]

# "eu" draws the European Commission's official AI labels.
AI_LABEL_ICON_SET = "eu"
```

Those two keys are the whole integration. No URLs change, no services are added.

Prefer opt-in per URL instead? Skip `APP_CLASS`, add the filter to `FILTERS`, and put
`ai_label()` in the URLs that should carry a label.

Running an engine other than PIL? Compose your own:

```python
from thumbor_ai_label.engine import AiLabelEngineMixin
from my.engine import Engine as Base


class Engine(AiLabelEngineMixin, Base):
    pass
```

Everything is configured through `thumbor.conf`. The plugin adds no services, no
sidecars and no runtime of its own.

## Where AI provenance lives

Not in EXIF, despite the common assumption:

| Signal | Location | Detector |
|---|---|---|
| IPTC `DigitalSourceType` | XMP packet | `iptc` (primary) |
| C2PA / Content Credentials | JUMBF box | `c2pa` (presence-only, optional extra) |
| Tool names in free-text tags | EXIF | `exif` (weak fallback) |

Detectors are selected and ordered by config. They are registered through the
`thumbor_ai_label.detectors` entry point group, so a deployment can add its own —
for example a lookup against an internal DAM — without forking this package.

## Component 1 — the container scanner

`thumbor_ai_label.scan` lifts XMP, EXIF and JUMBF payloads out of a buffer. It has
no Thumbor import, so it can be tested and reused on its own.

```python
from thumbor_ai_label.scan import scan

result = scan(buffer)  # bytes, bytearray or memoryview
result.container  # Container.JPEG | PNG | WEBP | None
result.xmp  # list[bytes] - XMP packets
result.exif  # list[bytes] - starting at the TIFF header
result.jumbf  # list[bytes] - reassembled JUMBF boxes
result.has_any_metadata  # what the fail-closed policy keys off
result.truncated, result.notes  # how far the walk got, and why it stopped
```

The buffer is the one the Thumbor loader already holds, so a scan adds no I/O.

### Performance

The walk never decodes a pixel. JPEG stops at the first scan header; PNG and WebP
skip image data by length arithmetic. Cost tracks metadata size, not image size:

| Case | File | Median scan |
|---|---|---|
| 640×480 JPEG, XMP + EXIF | 0.1 MB | 4.9 µs |
| 2000×1500 JPEG, XMP + EXIF | 1.5 MB | 4.9 µs |
| 4000×3000 JPEG, XMP + EXIF | 6.5 MB | 4.9 µs |
| 4000×3000 WebP, XMP + EXIF | 7.0 MB | 3.6 µs |

**A 65× range in file size, no measurable change in scan time.** That flatness is the
claim; the absolute microseconds are machine-specific and not worth quoting back.
`tools/bench_scan.py` reproduces the table, and a test asserts the flatness, so a
regression that starts reading image data fails the suite rather than quietly slowing
things down.

### Handled beyond the obvious cases

- **Adobe Extended XMP** — reassembled across APP1 segments by offset; a gap yields
  the contiguous prefix plus a note rather than spliced-together invalid XML.
- **Multi-packet JUMBF** — APP11 packets reassembled per box instance in sequence order.
- **ImageMagick raw profiles** — hex-wrapped XMP/EXIF in PNG `tEXt`/`zTXt`/`iTXt`,
  common in pipelines that have passed through ImageMagick.
- **PNG metadata after IDAT** — legal, so the walk continues to IEND.
- **Bad PNG CRCs** — not a reason to discard a payload every other tool reads.

### Safety

The scanner runs on untrusted bytes inside a request path, so it **never raises** —
a corrupt or hostile file yields a partial result with `truncated` set and a note
explaining why. Byte budgets bound XMP, EXIF and JUMBF independently; zlib inflation
is capped against compression bombs; oversized Extended XMP is refused from its
declared length before anything is allocated. `RawSegment.__repr__` omits payloads,
which can carry GPS and creator data, so they stay out of logs and tracebacks.

The suite fuzzes ~10,500 mutated and truncated inputs across all three containers
asserting no exception escapes.

## Component 2 — detectors

`thumbor_ai_label.detect` turns scanned segments into a verdict. Detectors are
selected and ordered in config, and resolved through the
`thumbor_ai_label.detectors` entry point group:

```python
AI_LABEL_DETECTORS = ["iptc", "exif"]
```

A detector is any module or object exposing `NAME`, `REQUIRES` and `detect`.
`detect` may be sync or async — the built-ins are pure CPU work over bytes already
in memory, but a detector that calls another system (a DAM lookup) can await.
Publishing one from a separate package needs no fork:

```toml
[project.entry-points."thumbor_ai_label.detectors"]
house_dam = "my_package.detectors:dam_lookup"
```

### States

`NOT_AI` and `UNKNOWN` are deliberately distinct. `NOT_AI` is a positive assertion —
something in the file says a camera took this. `UNKNOWN` is the absence of any such
claim. The fail-closed policy treats them very differently, so collapsing them would
quietly defeat it. An IPTC term this build does not recognise resolves to `UNKNOWN`,
never to `NOT_AI`: an unfamiliar term must not read as a clean bill of health.

### Execution

Detectors run in configured order. One whose required segment kinds are absent is
skipped without being called. The run stops at the first HIGH-confidence verdict;
a LOW-confidence one never short-circuits, so a heuristic cannot pre-empt the
standard. A detector that raises is logged and ignored — it yields no claim rather
than taking down the request or suppressing the detectors behind it.

### `iptc` — the primary signal

Reads IPTC `DigitalSourceType`, reported at HIGH confidence. This is the only
signal that is both standardised and unambiguous: the field exists to state how
an image was made, so reading it is not inference.

Named for the schema, not the carrier — IPTC's provenance fields live in the XMP
packet, the way EXIF lives in APP1.

It uses no XML parser. The input is attacker-controllable, and an XML parser on
untrusted input invites entity-expansion and external-entity attacks; hardening one
costs more than the targeted scan, which is also faster. Tests assert a
billion-laughs payload is inert. The namespace *prefix* is discovered from the
packet rather than assumed, since `Iptc4xmpExt` is conventional but prefixes are
arbitrary in XML. UTF-8, UTF-16 and UTF-32 packets are all handled.

### `exif` — the weak fallback

**EXIF defines no field that means "this image is AI."** Unlike IPTC, which has
`DigitalSourceType` as a controlled vocabulary, nothing in the EXIF specification
carries a provenance assertion — there is no standard tag to read. Verified against
the full standard tag set: the only relevant tags are free-text fields that tools
happen to write their own name into.

So this detector reads **standard EXIF tags**, not vendor-private MakerNote data:

| Tag | Where |
|---|---|
| `Software`, `ProcessingSoftware` | IFD0 |
| `Make`, `Model` | IFD0 |
| `ImageDescription` | IFD0 |
| `XPComment` (UTF-16) | IFD0 |
| `UserComment` | Exif sub-IFD |
| `Artist`, `Copyright` | IFD0 |

The tags are standard; the *matching vocabulary* is what is vendor-specific. That
distinction is why the verdict is always LOW confidence — an assertion is being
inferred from a tool name, not read from a field that means what we need it to mean.

Both IFD0 and the Exif sub-IFD are walked, since `UserComment` — where generation
parameters are sometimes written — lives in the latter. The sub-IFD pointer is
followed exactly once, so a pointer loop cannot spin.

Patterns are deliberately narrow. A generic editor — `Adobe Photoshop 25.0` — must
never match, because most images through Photoshop are not AI and a false positive
labels a real photograph. Tests pin that for Photoshop, Lightroom, GIMP, darktable
and Capture One.

Evidence names the tag it came from and is tightly capped: `UserComment` can hold a
whole generation prompt, which does not belong in logs or on a public meta endpoint.

The parser is bounded, dependency-free and never raises on malformed input.

## Component 3 — policy, icons and the label

### How a request flows

| Stage | Where | What happens |
|---|---|---|
| Load | `engine.load()` | Scan the original bytes, park the result on the request |
| Detect | filter, post-transform | Run detectors against the scan (async, so a detector may call out) |
| Decide | `policy.decide()` | Turn findings into a label state, or none |
| Draw | `compose.apply_label()` | Size, place and composite the icon |

The engine hook exists because `engine.load()` is the only point in Thumbor's flow
that always sees the original file — both the storage-hit and loader paths converge
on it — so it works regardless of which loader or storage backend is configured, and
whether or not the source was cached. Only the scan happens there, because `load()`
is synchronous; detectors run in the filter, which is async.

The scan result is parked on the request, not the buffer, so nothing keeps a decoded
original alive. Thumbor builds a fresh `Context` per request and the engine is
constructed per context, so a verdict cannot leak between images. The verdict is
memoised, because a filter runs once per frame on an animated image and detection
should not repeat for every frame of a GIF.

### Fail-closed policy

| Situation | `strict` (default) | `relaxed` |
|---|---|---|
| AI asserted | label | label |
| Camera asserted (`NOT_AI`) | no label | no label |
| Provenance block present, inconclusive | `unknown` label | `unknown` label |
| EXIF only, no provenance block | `unknown` label | **no label** |
| No metadata at all | `unknown` label | no label |

The row that matters is EXIF-only. EXIF defines no provenance field, so an EXIF
block asserts nothing either way — counting it as "metadata present" would put an
unknown label on essentially every camera photograph ever taken. `relaxed` therefore
keys off blocks that *can* carry an assertion (XMP, JUMBF), which is where a
stripped or tampered claim would show up.

`AI_LABEL_MIN_CONFIDENCE` gates only the positive AI claim. A not-AI assertion is
honoured at any confidence, because discarding it would push the image into the
unknown bucket and label it — the opposite of what raising the bar was for.

### Icons

Three icon sets ship — `default`, `eu` and `eu-white` — each covering four states:
`ai_generated`, `ai_manipulated`, `ai_composite`, `unknown`. `NOT_AI` has no icon by
design: a positively identified photograph gets no label at all.

**Labels are not assumed to be square.** The official EU labels are icon-plus-text
lockups around 3:1, so `AI_LABEL_SIZE_RATIO`, `MIN_SIZE` and `MAX_SIZE` all describe
label *height*, and width follows the icon's own aspect ratio. A wide label on a narrow
crop is scaled down to fit rather than squashed — deforming an official mark would be
worse than shrinking it.

They are drawn from code (`tools/make_icons.py`) rather than committed as opaque
binaries, so the design is reviewable and reproducible, and no font has to be shipped
or licensed. A dark translucent disc sits behind a light glyph so the label reads over
any underlying image, and the states differ by glyph and ring shape as well as colour,
so the set survives greyscale and does not depend on colour vision.

In the `default` set, **the three AI variants only separate reliably at about 48 px and
up** — below that the ring detail collapses and only colour distinguishes them. The `eu`
sets do not have this problem, since they carry the words. If you stay on `default` and
your styles are mostly small, consider pointing all three at one icon:

```python
AI_LABEL_ICONS = {
    "ai_generated": "/etc/thumbor/icons/ai.png",
    "ai_manipulated": "/etc/thumbor/icons/ai.png",
    "ai_composite": "/etc/thumbor/icons/ai.png",
}
```

Overrides are validated and decoded once at startup, so a missing or corrupt path
fails loudly rather than becoming a broken image mid-request. Resized variants are
cached, since rescaling on every request would be the most expensive thing here.

### Sizing and placement

Label size tracks the **shorter** edge, so it carries the same visual weight on a
panorama as on a square crop. It is clamped between `AI_LABEL_MIN_SIZE` and
`AI_LABEL_MAX_SIZE`, and never allowed to outgrow its own margins.

Images whose shorter edge is below `AI_LABEL_MIN_IMAGE_SIZE` (default 120 px) get no
label: on a 64 px thumbnail it is an unreadable smudge that costs bytes and tells the
viewer nothing.

### When labelling fails

Labelling never takes image delivery down — a bad icon path would otherwise turn every
request into a 500. Failures are logged at error level. Set
`AI_LABEL_STRICT_ERRORS = True` to make them fatal instead, for deployments that
would rather serve nothing than serve an unlabelled image.

## Component 4 — always-on

Thumbor has no native "always run this filter" hook, so the plugin supplies one.
`AiLabelServiceApp` swaps in an `ImagingHandler` that wraps the per-request filters
factory, appending the label filter to every request's post-transform phase.

`Context.filters_factory` is built per request, so the wrapper is installed in the
handler's `initialize` and cannot leak between requests. No Thumbor handler code is
copied, so there is little to break on a Thumbor upgrade.

**The label is appended last, deliberately.** It is drawn after every other
post-transform filter, so a URL cannot blur, desaturate or overlay it away. A test
pins this by requesting `filters:blur(12)` and asserting the label survives.

An explicit `ai_label()` in a URL still works alongside always-on and does not double
draw: the draw guard is set on the *engine*, not the request, so a doubly-registered
filter paints once while an animated image still gets every frame labelled.

### Boot-time validation

`APP_CLASS` resolves all settings at startup, so a typo'd icon path, an unknown
detector name or an invalid enum surfaces when Thumbor starts rather than as images
quietly going out unlabelled. It logs and continues by default; `AI_LABEL_STRICT_ERRORS`
makes it refuse to start.

Startup also logs when labelling is effectively off — `AI_LABEL_ENABLED = False`, or an
empty detector list — because "no labels" and "no AI images" look identical from the
outside.


## Component 5 — the meta endpoint

Thumbor's `/meta/` endpoint returns JSON describing what an image request would
produce. The verdict is published there under a top-level `ai_label` key:

```
GET /unsafe/meta/600x400/photo.jpg
```

```json
{
  "thumbor": { "source": {...}, "operations": [...], "target": {...} },
  "ai_label": {
    "label": "ai_generated",
    "reason": "ai_asserted",
    "policy": "strict",
    "labelled": true,
    "disclosure": "AI generated"
  }
}
```

A sibling of `thumbor` rather than a member of it — that namespace is Thumbor's, and a
future key of theirs must not be able to collide with ours.

### `labelled` is the field that matters

It says whether an image request at those dimensions would actually carry a visible
label. Below `AI_LABEL_MIN_IMAGE_SIZE` nothing is drawn, so:

```json
{ "label": "ai_generated", "labelled": false }
```

means the image *is* AI but the pixels do not say so — and the disclosure you write into
the DOM is the **only** disclosure, not a supplement to a visible one. Detection and
drawing are separate decisions and this reports both.

### Diagnostics are off by default

`detector`, `confidence`, `evidence` and `generator` appear only with
`AI_LABEL_META_VERBOSE = True`. `evidence` can carry a fragment of a generation prompt
read out of EXIF `UserComment`, and this endpoint is publicly reachable.

### Localisation

`disclosure` is English by default. Override per state:

```python
AI_LABEL_META_DISCLOSURES = {
    "ai_generated": "KI-generiert",
    "ai_manipulated": "KI-bearbeitet",
    "unknown": "Herkunft nicht feststellbar",
}
```

Consumers wanting full control should map the machine-readable `label` themselves and
ignore `disclosure` entirely.

Note that the `unknown` disclosure is deliberately not phrased as an AI claim. Someone
relying on a screen reader cannot judge the image for themselves, and telling them it is
AI on evidence that only says "provenance could not be established" would mislead
exactly the people this field exists to serve.

### How it is wired

`JSONEngine.read()` builds the response and offers no hook, so the handler wraps
`_load_results` and the verdict is merged into the serialised payload — a JSON
round-trip, not a string splice, so a change to Thumbor's own payload cannot corrupt it.
JSONP via `META_CALLBACK_NAME` is unwrapped and rewrapped.

`_load_results` runs in Thumbor's thread pool, off the event loop, so nothing there can
await. The verdict is read from where the label filter already stored it, and
`after_transform` guarantees it exists first. Injection failure returns the original
response untouched: a broken labelling feature must not break an endpoint clients rely
on.


## Configuration reference

| Key | Default | Meaning |
|---|---|---|
| `AI_LABEL_ENABLED` | `True` | Master switch |
| `AI_LABEL_DETECTORS` | `None` | Ordered detector names; `None` uses the default order |
| `AI_LABEL_POLICY` | `"strict"` | `strict` or `relaxed` |
| `AI_LABEL_MIN_CONFIDENCE` | `"low"` | Lowest confidence that may raise an AI label |
| `AI_LABEL_ICON_SET` | `"default"` | `default`, `eu`, or `eu-white` |
| `AI_LABEL_ICONS` | `{}` | Per-state icon path overrides; win over the set |
| `AI_LABEL_OPACITY` | `100` | Label opacity, 0–100 |
| `AI_LABEL_POSITION` | `"bottom-right"` | Corner, or `center` |
| `AI_LABEL_SIZE_RATIO` | `0.14` | Label **height** as a fraction of the shorter edge |
| `AI_LABEL_MIN_SIZE` / `MAX_SIZE` | `20` / `96` | Height clamps, in pixels |
| `AI_LABEL_MIN_IMAGE_SIZE` | `120` | Below this shorter edge, no label |
| `AI_LABEL_MARGIN_RATIO` | `0.04` | Margin as a fraction of the shorter edge |
| `AI_LABEL_MIN_MARGIN` | `3` | Smallest margin, in pixels |
| `AI_LABEL_STRICT_ERRORS` | `False` | Make labelling failures fatal |
| `AI_LABEL_META` | `True` | Publish the verdict on `/meta/` |
| `AI_LABEL_META_VERBOSE` | `False` | Include detector, confidence, evidence, generator |
| `AI_LABEL_META_DISCLOSURES` | `None` | Per-state disclosure strings; `None` uses English |


## Known constraint

Thumbor has no XMP support of any kind, and `PRESERVE_EXIF_INFO` defaults to `False`,
so provenance metadata is stripped from every derivative Thumbor generates. The label
this plugin draws is therefore the only surviving signal on the output image.

This is a property of the deployment, not a gap in the plugin. Writing metadata is
deliberately out of scope: the plugin reads to decide which label to show, and never
writes.

It also does not affect your Article 50(4) position, which is a *human-perceptible*
disclosure obligation and is what the label satisfies. Machine-readable marking under
Article 50(2) binds the **provider** of the AI system, not a publisher redistributing
its output. If you nonetheless want the provider's marking to survive Thumbor — good
ecosystem practice, and it keeps downstream detection working — that belongs in the
publishing pipeline rather than here.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Contributions are Apache-2.0 by submission and
there is no CLA.

The most useful contribution is not a patch: it is a **real image from a real AI tool**
whose provenance this reads wrongly. Every fixture here is synthetic, and that limit has
already hidden one genuine bug.

```bash
python -m venv .venv && .venv/bin/pip install -e '.[dev,thumbor]'
```

```bash
.venv/bin/python -m pytest --cov=thumbor_ai_label --cov-report=term-missing
```

### Versioning

The version is derived from git tags by `setuptools-scm` — there is no version string
to edit anywhere. Release by tagging:

```bash
git tag v0.1.0 && git push --tags
```

| Repository state | Version produced |
|---|---|
| Tagged `v0.1.0` | `0.1.0` |
| One commit past that tag | `0.1.1.dev1` |
| Committed, never tagged | `0.0.0.dev1` |
| No commits, or a tarball with no git metadata | `0.0.0.dev0` |

`local_scheme = "no-local-version"` is set deliberately: setuptools-scm otherwise
appends a `+g1a2b3c4` local segment to untagged builds, and PyPI rejects any version
carrying one — so the default would make CI artefacts silently unpublishable.

`.git_archival.txt` and `.gitattributes` let a GitHub source tarball, which has no
`.git` directory, still resolve its version rather than falling back.

## Licence

Apache License 2.0 — see [LICENSE](LICENSE).

Use it for anything: private projects, internal tooling, commercial products, hosted
services. No fee, no permission needed, no copyleft. Apache-2.0 also grants an express
patent licence, which MIT does not, so it is the safer choice for corporate adopters.

Two obligations, both light: keep the licence and copyright notice with any copy you
distribute, and state what you changed if you ship a modified version.

Bundled European Commission AI-labelling icons carry the Commission's own terms and are
not covered by the above — see [THIRD-PARTY.md](THIRD-PARTY.md).

## Sponsoring

This is licensed permissively on purpose. A compliance tool is worth more the more
widely it is used, and a licence that fenced off commercial users would have fenced off
almost everyone who actually runs Thumbor.

That leaves development unfunded, so: **if you run this in a commercial product — and
particularly if you offer AI labelling as a feature your customers pay for — please
sponsor its development.** It is a request, not a licence condition; nothing here is
enforced and nothing is withheld from anyone who does not.

[GitHub Sponsors](https://github.com/sponsors/IT-Cru)

Non-financial contributions are worth as much: real-world images whose provenance
metadata this fails to read are the single most useful thing you can send, since every
fixture in the test suite is synthetic.
