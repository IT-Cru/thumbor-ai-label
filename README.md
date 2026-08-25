# thumbor-ai-label

[![CI](https://github.com/IT-Cru/thumbor-ai-label/actions/workflows/ci.yml/badge.svg)](https://github.com/IT-Cru/thumbor-ai-label/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.10%20%E2%80%93%203.14-blue)](pyproject.toml)
[![Thumbor](https://img.shields.io/badge/thumbor-7.8%2B-blue)](https://github.com/thumbor/thumbor)
[![Licence](https://img.shields.io/badge/licence-Apache--2.0-green)](LICENSE)

A Thumbor plugin that reads AI provenance metadata from the source image and draws a
visible AI label on every generated image style.

![Three images: one labelled AI GENERATED, one labelled AI MODIFIED, one untouched](docs/example.png)

> **Pre-1.0.** Everything below works and is covered by tests, but the configuration
> surface may still change.

## Why this exists — EU AI Act Article 50

**Article 50 has applied since 2 August 2026.** Non-compliance carries fines of up to
€15 million or 3% of worldwide annual turnover.

The plugin targets **Article 50(4)**, the *deployer* obligation: anyone publishing a
deep fake — AI-generated or manipulated image content that would falsely appear
authentic — must disclose that it was artificially generated or manipulated. Article
50(5) requires that disclosure "in a clear and distinguishable manner at the latest at
the time of the first interaction or exposure."

A publisher is a **deployer**, not a provider, and that distinction decides what you owe:

| | Article 50(2) — providers | Article 50(4) — deployers |
|---|---|---|
| Who | Whoever builds and ships the AI system | Whoever publishes the output |
| What | **Machine-readable** marking | **Human-perceptible** disclosure |
| Applies to a publisher? | Usually no | **Yes** |

The Commission is explicit that deployers **cannot rely solely on machine-readable
markings embedded by providers**. The Code of Practice on Transparency of AI-Generated
Content asks for a **"clearly visible, fixed icon"** on images, directly embedded.

A label burnt into every derivative is exactly that: visible, fixed, embedded, present at
first exposure, and — because it is composited after every other filter — not removable
through URL manipulation.

### What it covers, and what it does not

| Requirement | Status |
|---|---|
| Visible, human-perceptible label | ✅ Burnt into every derivative |
| Directly embedded in the image | ✅ Not a CSS overlay a client can drop |
| Present at first exposure | ✅ Every style carries it |
| Survives downstream filtering | ✅ Composited last; `blur()` cannot erase it |
| Generated vs modified distinguished | ✅ Separate states and icons |
| Official EU icon set | ✅ Bundled — `AI_LABEL_ICON_SET = "eu"` |
| Icon paired with a text label | ✅ The EU labels read "AI GENERATED" / "AI MODIFIED" |
| Alt text / ARIA for assistive tech | ⚠️ Verdict published on `/meta/`; your CMS must use it |
| Deciding *which* images are AI | ⚠️ Only detects what the metadata declares |

**It over-labels, deliberately.** Article 50(4) covers only *deep fakes* and exempts
evidently creative, satirical or artistic work. The plugin cannot judge realism or intent,
so it labels every image whose metadata declares AI involvement. Over-disclosure is the
safer direction legally, with an editorial cost you should weigh.

**It is only the automated half.** The plugin sees what the metadata says. An AI image
arriving with its provenance stripped passes through unlabelled. The Code of Practice
expects deployers to combine automated detection with human oversight.

> This is a technical mapping onto published requirements, not legal advice. Have your own
> counsel confirm what Article 50 requires of your organisation.

## Install

Requires **Thumbor 7.8+** and **Python 3.10+**. Reads JPEG, PNG and WebP; AVIF and HEIC
are not yet supported. The bundled engine wraps Thumbor's PIL engine.

```bash
pip install thumbor-ai-label
```

Two keys in `thumbor.conf` are the whole integration:

```python
# Labels every image, with no change to any URL.
APP_CLASS = "thumbor_ai_label.app.AiLabelServiceApp"

# The engine hook is what sees the original bytes; without it nothing is detected.
ENGINE = "thumbor_ai_label.engine"
```

No URLs change, no services are added. Labelling costs well under a millisecond per
request — the metadata scan never decodes a pixel, and its cost does not grow with image
size.

Running an engine other than PIL? Compose your own:

```python
from thumbor_ai_label.engine import AiLabelEngineMixin
from my.engine import Engine as Base


class Engine(AiLabelEngineMixin, Base):
    pass
```

Prefer opt-in per URL instead? Skip `APP_CLASS`, add `thumbor_ai_label.filters.ai_label`
to `FILTERS`, and put `ai_label()` in the URLs that should carry a label.

### Verifying it works

[`tests/images/`](tests/images/) holds 24 images covering every detection and policy case,
with a manifest of expected outcomes. Point a file loader at them and request a few — see
[its README](tests/images/README.md).

## Configuration

### Policy — the setting that matters most

`AI_LABEL_POLICY` decides what happens when nothing asserts how an image was made.

| Situation | `strict` (default) | `relaxed` |
|---|---|---|
| AI asserted | label | label |
| Camera asserted | no label | no label |
| Provenance block present, inconclusive | `unknown` | `unknown` |
| EXIF only, no provenance block | `unknown` | **no label** |
| No metadata at all | `unknown` | no label |

The row that decides your deployment is **EXIF only**. EXIF defines no provenance field,
so an EXIF block asserts nothing either way — and counting it as "metadata present" puts
an `unknown` label on essentially every camera photograph ever taken. On a legacy archive
`strict` will label most of your library.

**The `unknown` label has no basis in Article 50.** The law obliges you to disclose content
you *know* is AI, not content whose provenance you cannot establish. `strict` is a
defensive posture, not a legal requirement, and it may mislead readers in its own way.

### Detectors

Selected and ordered by config, resolved through the `thumbor_ai_label.detectors` entry
point group, so a deployment can add its own — a DAM lookup, a house heuristic — without
forking.

```python
AI_LABEL_DETECTORS = ["iptc", "exif"]
```

#### `iptc` — the primary signal

Reads IPTC `DigitalSourceType` at **HIGH** confidence. This is the only signal that is both
standardised and unambiguous: the field exists to state how an image was made, so reading
it is not inference.

Named for the schema, not the carrier — IPTC's provenance fields live in the XMP packet,
the way EXIF lives in APP1. Handles the attribute and element forms, arbitrary namespace
prefixes, UTF-8/16/32, and Adobe Extended XMP split across segments. It uses **no XML
parser**: the input is attacker-controllable, and hardening a parser against
entity-expansion and XXE costs more than a targeted scan that is also faster.

| Term | State |
|---|---|
| `trainedAlgorithmicMedia` | `ai_generated` |
| `compositeWithTrainedAlgorithmicMedia` | `ai_composite` |
| `algorithmicallyEnhanced` | `ai_manipulated` |
| `digitalCapture`, `digitalArt`, `compositeCapture`, … | no label |
| anything unrecognised | `unknown` |

An unfamiliar term resolves to `unknown`, never to "not AI". A term this build has not
heard of must not read as a clean bill of health.

#### `exif` — the weak fallback

**EXIF defines no field that means "this image is AI."** Unlike IPTC, nothing in the
specification carries a provenance assertion. What EXIF has is free-text fields that tools
write their own name into: `Software`, `ProcessingSoftware`, `Make`, `Model`,
`ImageDescription`, `XPComment`, and `UserComment` in the Exif sub-IFD.

So this detector reads **standard EXIF tags**, not vendor-private MakerNote data. The tags
are standard; the *matching vocabulary* is what is vendor-specific. That is why the verdict
is always **LOW** confidence — an assertion is inferred from a tool name, not read from a
field that means what we need it to mean.

Patterns are deliberately narrow. A generic editor — `Adobe Photoshop 25.0` — must never
match, because most images through Photoshop are not AI and a false positive labels a real
photograph. Tests pin that for Photoshop, Lightroom, GIMP, darktable and Capture One.

`AI_LABEL_MIN_CONFIDENCE` gates only the positive AI claim. A not-AI assertion is honoured
at any confidence, because discarding it would push the image into the unknown bucket and
label it — the opposite of what raising the bar was for.

### Icon variants

Three sets ship, each covering `ai_generated`, `ai_manipulated`, `ai_composite` and
`unknown`. `NOT_AI` has no icon by design: a positively identified photograph gets no
label at all.

```python
AI_LABEL_ICON_SET = "eu"  # official EU labels, dark, for light imagery
AI_LABEL_ICON_SET = "eu-white"  # official EU labels, light, for dark imagery
AI_LABEL_ICON_SET = "default"  # this plugin's own marks
```

The `eu` sets are the European Commission's harmonised icons, published 10 June 2026 and
free to use without attribution. **Their use is optional; the disclosure obligation is
not.**

| Official mark | Plugin state |
|---|---|
| AI GENERATED | `ai_generated` |
| AI MODIFIED | `ai_manipulated`, `ai_composite` |
| *(none — see below)* | `unknown` |

`ai_composite` maps to **AI MODIFIED** because a composite containing AI elements is
exactly "pre-existing human-made content partially modified with AI".

**`unknown` never draws an official EU mark.** Those marks assert that content *is* AI.
Using one on an image whose provenance merely could not be established would make a claim
the evidence does not support, so that state keeps this plugin's own neutral icon.

Labels are **not assumed to be square** — the EU marks are icon-plus-text lockups around
3:1, so size settings describe *height* and width follows the icon. Per-state overrides:

```python
AI_LABEL_ICONS = {"ai_generated": "/etc/thumbor/icons/house-style.png"}
```

Overrides are validated and decoded once at startup, so a missing or corrupt path fails
loudly rather than becoming a broken image mid-request.

> The Commission notes that use of these icons by non-signatories of the Code of Practice
> "should not be construed as signaling of their adherence to the code", and that
> signatories must follow its placement specifications.

### The meta endpoint

The verdict is published on Thumbor's `/meta/` endpoint under a top-level `ai_label` key.
**This is how a CMS obtains the verdict to write alt text or an ARIA label**, which is what
Article 50(5) accessibility asks for and what a label burnt into pixels cannot provide.

```
GET /unsafe/meta/600x400/photo.jpg
```

```json
{
  "thumbor": { "source": {}, "operations": [], "target": {} },
  "ai_label": {
    "label": "ai_generated",
    "reason": "ai_asserted",
    "policy": "strict",
    "labelled": true,
    "disclosure": "AI generated"
  }
}
```

**`labelled` is the field that matters.** It says whether an image request at those
dimensions would actually carry a visible mark. Below `AI_LABEL_MIN_IMAGE_SIZE` nothing is
drawn, so `{"label": "ai_generated", "labelled": false}` means the image *is* AI but the
pixels do not say so — and the disclosure you write into the DOM is the **only** one.

`disclosure` is English by default and overridable per state via
`AI_LABEL_META_DISCLOSURES`. Consumers wanting full control should map the
machine-readable `label` themselves.

Diagnostics — `detector`, `confidence`, `evidence`, `generator` — appear only with
`AI_LABEL_META_VERBOSE = True`. `evidence` can carry a fragment of a generation prompt read
out of EXIF `UserComment`, and this endpoint is publicly reachable.

### Reference

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
| `AI_LABEL_STRICT_ERRORS` | `False` | Make labelling failures fatal instead of logged |
| `AI_LABEL_META` | `True` | Publish the verdict on `/meta/` |
| `AI_LABEL_META_VERBOSE` | `False` | Include detector, confidence, evidence, generator |
| `AI_LABEL_META_DISCLOSURES` | `None` | Per-state disclosure strings; `None` uses English |

Sizes track the **shorter** edge, so a label carries the same visual weight on a panorama
as on a square crop. Images below `AI_LABEL_MIN_IMAGE_SIZE` get no label: on a 64 px
thumbnail it is an unreadable smudge that costs bytes and tells the viewer nothing.

## Known constraints

**Thumbor strips provenance metadata from every derivative.** It has no XMP support of any
kind, and `PRESERVE_EXIF_INFO` defaults to `False`. The label this plugin draws is
therefore the only surviving signal on the output image.

This is a property of the deployment, not a gap in the plugin, and it does not affect your
Article 50(4) position — that is a *human-perceptible* obligation, which the label
satisfies. Machine-readable marking under 50(2) binds the **provider** of the AI system,
not a publisher redistributing its output. The plugin is deliberately **read-only**: it
reads metadata to decide which label to show, and never writes.

**Accessibility needs your CMS to cooperate.** A label burnt into pixels is invisible to a
screen reader, and Thumbor does not control the surrounding HTML. The plugin closes its
half by publishing the verdict on `/meta/`; something has to read it and write the markup.

**Result storage caches labelled derivatives.** A policy change will not reach
already-cached images without invalidation.

**No real-world AI images have been tested.** Every fixture is synthetic. See
[CONTRIBUTING.md](CONTRIBUTING.md) — this is the most useful gap you could help close.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md), and [SECURITY.md](SECURITY.md) for reporting a
vulnerability privately. Contributions are Apache-2.0 by submission and
there is no CLA.

The most useful contribution is not a patch: it is a **real image from a real AI tool**
whose provenance this reads wrongly. Every fixture here is synthetic, and that limit has
already hidden one genuine bug.

```bash
python -m venv .venv && .venv/bin/pip install -e '.[dev,thumbor]'
.venv/bin/python -m pytest --cov=thumbor_ai_label --cov-report=term-missing
```

Versions come from git tags via `setuptools-scm`; there is no version string to edit.
Release by tagging: `git tag v0.1.0 && git push --tags`.

## Sponsoring

This is licensed permissively on purpose. A compliance tool is worth more the more widely
it is used, and a licence that fenced off commercial users would have fenced off almost
everyone who actually runs Thumbor.

That leaves development unfunded, so: **if you run this in a commercial product — and
particularly if you offer AI labelling as a feature your customers pay for — please
sponsor its development.** It is a request, not a licence condition; nothing is enforced
and nothing is withheld from anyone who does not.

[GitHub Sponsors](https://github.com/sponsors/IT-Cru)

## Licence

Apache License 2.0 — see [LICENSE](LICENSE).

Use it for anything: private projects, internal tooling, commercial products, hosted
services. No fee, no permission needed, no copyleft. Apache-2.0 also grants an express
patent licence, which MIT does not, so it is the safer choice for corporate adopters.

Two obligations, both light: keep the licence and copyright notice with any copy you
distribute, and state what you changed if you ship a modified version.

Bundled European Commission AI-labelling icons carry the Commission's own terms and are not
covered by the above — see [THIRD-PARTY.md](THIRD-PARTY.md).
