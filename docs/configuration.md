# Configuration

Everything is set in `thumbor.conf`. The plugin adds no services, no sidecars and no
runtime of its own.

## Policy

`AI_LABEL_POLICY` decides what happens when **nothing asserts how an image was made**. It
is the one setting that materially changes what your readers see.

| Situation | `strict` (default) | `relaxed` |
|---|---|---|
| AI asserted | label | label |
| Camera asserted | no label | no label |
| Provenance block present, inconclusive | `unknown` | `unknown` |
| EXIF only, no provenance block | `unknown` | **no label** |
| No metadata at all | `unknown` | no label |

The row that decides your deployment is **EXIF only**. EXIF defines no provenance field,
so an EXIF block asserts nothing either way — counting it as "metadata present" puts an
`unknown` label on essentially every camera photograph ever taken. `DigitalSourceType` is
a young field, so images predating it carry no provenance at all.

!!! warning "`unknown` has no basis in Article 50"
    The law obliges you to disclose content you *know* is AI, not content whose provenance
    you cannot establish. `strict` is a defensive posture, not a legal requirement, and it
    may mislead readers in its own way.

### Measure before you choose

Both policies are defensible; which suits you depends on what your source images actually
carry. Point a second Thumbor at the same source storage and ask it. **Meta requests never
draw a label**, so a measurement instance cannot alter an image even if production traffic
reaches it by mistake.

```bash
while read -r path; do
  curl -s "http://localhost:8888/unsafe/meta/600x400/$path" \
    | jq -r '.ai_label | if .label == null then "no label" else .label end'
done < paths.txt | sort | uniq -c | sort -rn
```

Run it under each policy. Against this project's own 24 fixtures:

| Verdict | `strict` | `relaxed` |
|---|---|---|
| `ai_generated` | 12 | 12 |
| `ai_manipulated` / `ai_composite` | 1 / 1 | 1 / 1 |
| `unknown` | **6** | **3** |
| no label | **4** | **7** |

Three move — those carrying only EXIF, or nothing. Across real source images that gap is
far wider, and it is the whole decision.

Worth counting too: how often `labelled` is `false` while `label` is set. Those are images
the plugin identified but which are too small to carry a visible mark, so the disclosure
your CMS writes is the only one a reader gets.

```bash
while read -r path; do
  curl -s "http://localhost:8888/unsafe/meta/120x80/$path" \
    | jq -r '.ai_label | select(.label != null) | .labelled | tostring'
done < paths.txt | sort | uniq -c
```

??? note "If a second instance is impractical"
    Setting `AI_LABEL_MIN_IMAGE_SIZE` above any image you serve gives byte-identical
    output to the plugin being off while detection still runs.

    Do not leave it in place: it reads like a fat-fingered threshold, and a compliance
    tool that looks enabled while marking nothing is worse than one that is plainly off.

    `AI_LABEL_OPACITY = 0` looks equivalent and is not — it reports `labelled: true` while
    drawing nothing, so the meta payload lies.

## Detectors

Selected and ordered by config, resolved through an entry point group so a deployment can
add its own without forking. See [Extending](extending.md).

```python
AI_LABEL_DETECTORS = ["iptc", "exif"]
```

Detectors run in order and stop at the first **HIGH**-confidence verdict. A LOW-confidence
one never short-circuits, so a heuristic cannot pre-empt the standard.

### `iptc` — the primary signal

Reads IPTC `DigitalSourceType` at **HIGH** confidence. The only signal that is both
standardised and unambiguous: the field exists to state how an image was made, so reading
it is not inference.

Named for the schema, not the carrier — IPTC's provenance fields live in the XMP packet,
the way EXIF lives in APP1.

| Term | State |
|---|---|
| `trainedAlgorithmicMedia` | `ai_generated` |
| `compositeWithTrainedAlgorithmicMedia` | `ai_composite` |
| `algorithmicallyEnhanced` | `ai_manipulated` |
| `digitalCapture`, `digitalArt`, `compositeCapture`, … | no label |
| anything unrecognised | `unknown` |

An unfamiliar term resolves to `unknown`, **never** to "not AI". A term this build has not
heard of must not read as a clean bill of health.

### `exif` — the weak fallback

**EXIF defines no field that means "this image is AI."** Nothing in the specification
carries a provenance assertion. What it has is free-text fields that tools write their own
name into: `Software`, `ProcessingSoftware`, `Make`, `Model`, `ImageDescription`,
`XPComment`, and `UserComment` in the Exif sub-IFD.

So this detector reads **standard EXIF tags**, not vendor-private MakerNote data. The tags
are standard; the *matching vocabulary* is what is vendor-specific. That is why the verdict
is always **LOW** confidence — an assertion is inferred from a tool name, not read from a
field that means what we need it to mean.

Patterns are deliberately narrow. A generic editor — `Adobe Photoshop 25.0` — must never
match, because most images through Photoshop are not AI and a false positive labels a real
photograph.

`AI_LABEL_MIN_CONFIDENCE` gates only the positive AI claim. A not-AI assertion is honoured
at any confidence, because discarding it would push the image into the unknown bucket and
label it — the opposite of what raising the bar was for.

## Icon variants

Three sets ship, each covering `ai_generated`, `ai_manipulated`, `ai_composite` and
`unknown`. `NOT_AI` has no icon by design: a positively identified photograph gets no label
at all.

```python
AI_LABEL_ICON_SET = "eu"        # official EU labels, dark, for light imagery
AI_LABEL_ICON_SET = "eu-white"  # official EU labels, light, for dark imagery
AI_LABEL_ICON_SET = "default"   # this plugin's own marks
```

The `eu` sets are the European Commission's harmonised icons, published 10 June 2026 and
free to use without attribution. **Their use is optional; the disclosure obligation is
not.**

| Official mark | Plugin state |
|---|---|
| AI GENERATED | `ai_generated` |
| AI MODIFIED | `ai_manipulated`, `ai_composite` |
| *(none)* | `unknown` |

`ai_composite` maps to **AI MODIFIED** because a composite containing AI elements is
exactly "pre-existing human-made content partially modified with AI".

!!! danger "`unknown` never draws an official EU mark"
    Those marks assert that content *is* AI. Using one on an image whose provenance merely
    could not be established would make a claim the evidence does not support, so that
    state keeps this plugin's own neutral icon.

Labels are **not assumed to be square** — the EU marks are icon-plus-text lockups around
3:1, so size settings describe *height* and width follows the icon. Per-state overrides:

```python
AI_LABEL_ICONS = {"ai_generated": "/etc/thumbor/icons/house-style.png"}
```

Overrides are validated and decoded once at startup, so a missing or corrupt path fails
loudly rather than becoming a broken image mid-request.

## The meta endpoint

The verdict is published on Thumbor's `/meta/` endpoint under a top-level `ai_label` key.
**This is how a CMS obtains the verdict to write alt text or an ARIA label**, which is what
Article 50(5) accessibility asks for and what a label burnt into pixels cannot provide.

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

`disclosure` is English by default and overridable per state:

```python
AI_LABEL_META_DISCLOSURES = {
    "ai_generated": "KI-generiert",
    "ai_manipulated": "KI-bearbeitet",
    "unknown": "Herkunft nicht feststellbar",
}
```

The `unknown` string is deliberately not phrased as an AI claim. Someone relying on a
screen reader cannot judge the image for themselves.

!!! warning "Diagnostics are off by default"
    `detector`, `confidence`, `evidence` and `generator` appear only with
    `AI_LABEL_META_VERBOSE = True`. `evidence` can carry a fragment of a generation prompt
    read out of EXIF `UserComment`, and this endpoint is publicly reachable.

## Reference

Pulled directly from the project README, so the two cannot drift.

--8<-- "README.md:config-reference"

Sizes track the **shorter** edge, so a label carries the same visual weight on a panorama
as on a square crop. Images below `AI_LABEL_MIN_IMAGE_SIZE` get no label: on a 64 px
thumbnail it is an unreadable smudge that costs bytes and tells the viewer nothing.
