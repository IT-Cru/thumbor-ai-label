# EU AI Act Article 50

!!! note "Not legal advice"
    This is a technical mapping of the plugin's behaviour onto published requirements and
    guidance. Have your own counsel confirm what Article 50 requires of your organisation.

**Article 50 has applied since 2 August 2026.** Non-compliance carries fines of up to
€15 million or 3% of worldwide annual turnover.

## Provider or deployer

The distinction decides what you owe, and it is the one most easily got wrong.

| | Article 50(2) — providers | Article 50(4) — deployers |
|---|---|---|
| Who | Whoever builds and ships the AI system | Whoever publishes the output |
| What | **Machine-readable** marking | **Human-perceptible** disclosure |
| Applies to a publisher? | Usually no | **Yes** |

A publisher redistributing AI output is normally *not* the provider, so 50(2) is usually
not their obligation. Article 50(4) is: anyone publishing a deep fake — AI-generated or
manipulated image content that would falsely appear authentic — must disclose that it was
artificially generated or manipulated.

Article 50(5) adds that the disclosure must be made "in a clear and distinguishable manner
at the latest at the time of the first interaction or exposure", and must meet
accessibility requirements.

!!! important "Machine-readable marking is not a substitute"
    The Commission is explicit that deployers **cannot rely solely on machine-readable
    markings embedded by providers**. Human-perceptible disclosure is required.

    This matters here because Thumbor strips provenance metadata from every derivative it
    generates — see [Known constraints](#known-constraints). That does not affect your
    50(4) position, because 50(4) was never about metadata.

The Code of Practice on Transparency of AI-Generated Content asks for a **"clearly visible,
fixed icon"** on images, directly embedded. A label burnt into every derivative is exactly
that.

## What this plugin covers

| Requirement | Status |
|---|---|
| Visible, human-perceptible label | :material-check: Burnt into every derivative |
| Directly embedded in the image | :material-check: Not a CSS overlay a client can drop |
| Present at first exposure | :material-check: Every style carries it |
| Survives downstream filtering | :material-check: Composited last; `blur()` cannot erase it |
| Generated vs modified distinguished | :material-check: Separate states and icons |
| Official EU icon set | :material-check: Bundled |
| Icon paired with a text label | :material-check: The EU labels carry the words |
| Alt text / ARIA for assistive tech | :material-alert: Published on `/meta/`; your CMS must use it |
| Deciding *which* images are AI | :material-alert: Only detects what metadata declares |

## Honest limitations

### It over-labels, deliberately

Article 50(4) covers only **deep fakes** — content that "would falsely appear to a person
to be authentic" — and exempts evidently creative, satirical or artistic work. The plugin
cannot judge realism or intent, so it labels every image whose metadata declares AI
involvement. Over-disclosure is the safer direction legally, with an editorial cost you
should weigh.

### `unknown` has no legal basis

The law obliges you to disclose content you *know* is AI, not content whose provenance you
cannot establish. The default `strict` policy labels everything unproven, which on older
content is most of it — an AI-adjacent mark on genuine photographs.

That is a defensive posture, not a requirement. See
[Policy](configuration.md#policy), and measure it against your own images before deciding.

### It is only the automated half

The plugin sees what the metadata says. An AI image arriving with its provenance stripped
passes through unlabelled. The Code of Practice expects deployers to combine automated
detection with **human oversight**.

### Accessibility needs your CMS

A label burnt into pixels is invisible to a screen reader, and Thumbor serves images — it
does not control the surrounding HTML. The plugin closes its half by publishing the verdict
on [the meta endpoint](configuration.md#the-meta-endpoint). Something has to read it and
write the alt text or ARIA label.

## The official EU icons

The Commission published a harmonised icon set on 10 June 2026 — free to use, no
attribution required. **Their use is optional; the disclosure obligation is not.** They
ship with this plugin; see [icon variants](configuration.md#icon-variants).

!!! quote "Two caveats from the Commission's own guidance"
    Signatories of the Code of Practice must use these icons in accordance with its
    placement specifications.

    Use of these icons by non-signatories "should not be construed as signaling of their
    adherence to the code". Displaying them does not enrol you in anything.

## Known constraints

**Thumbor strips provenance metadata from every derivative.** It has no XMP support of any
kind, and `PRESERVE_EXIF_INFO` defaults to `False`. The label this plugin draws is
therefore the only surviving signal on the output image.

This is a property of the deployment, not a gap in the plugin, and it does not affect your
Article 50(4) position. The plugin is deliberately **read-only**: it reads metadata to
decide which label to show, and never writes.

**Result storage caches labelled derivatives.** A policy change will not reach
already-cached images without invalidation.

## Sources

- [Article 50](https://artificialintelligenceact.eu/article/50/) ·
  [Recital 133](https://artificialintelligenceact.eu/recital/133/) ·
  [Recital 134](https://artificialintelligenceact.eu/recital/134/)
- [Commission FAQ on Article 50 transparency obligations](https://digital-strategy.ec.europa.eu/en/faqs/transparency-obligations-under-article-50-ai-act)
- [Code of Practice on marking and labelling AI-generated content](https://digital-strategy.ec.europa.eu/en/news/commission-publishes-code-practice-marking-and-labelling-ai-generated-content)
- [EU Icons for labelling AI-generated content](https://digital-strategy.ec.europa.eu/en/policies/eu-icons-labelling-ai-generated-content)
