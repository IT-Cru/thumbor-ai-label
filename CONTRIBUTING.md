# Contributing

## Licensing of contributions

This project is licensed under [Apache-2.0](LICENSE), and Apache-2.0 §5 handles inbound
contributions on its own:

> Unless You explicitly state otherwise, any Contribution intentionally submitted for
> inclusion in the Work by You to the Licensor shall be under the terms and conditions
> of this License, without any additional terms or conditions.

In practice:

- **You keep the copyright in your own contribution.** Nothing is assigned away.
- **Your contribution is licensed under Apache-2.0** by the act of submitting it.
- **There is no CLA to sign.** Nothing to print, nothing to email, no bot to appease.

If you want to contribute under different terms, say so explicitly in the pull request
before it is merged.

One consequence worth stating openly, because it constrains the maintainers rather than
you: with no CLA, this project **cannot be relicensed** without the consent of everyone
who has contributed. That is a deliberate trade. It keeps the barrier to contributing at
zero, and it means Apache-2.0 is effectively permanent.

### Third-party assets

The European Commission icons under `src/thumbor_ai_label/icons/eu/` and `eu-white/` are
**not** covered by this project's licence and are not ours to relicense. See
[THIRD-PARTY.md](THIRD-PARTY.md). Do not edit them; run `tools/fetch_eu_icons.py` if
they need refreshing.

If you add a dependency or asset with its own terms, record it in `THIRD-PARTY.md`, not
in `NOTICE`. Apache-2.0 §4(d) makes everything in `NOTICE` binding on every derivative
work anyone distributes, forever — so it holds only what genuinely must travel.

## The most useful thing you can contribute

**Real images from real AI tools.** Every fixture in `tests/images/` is synthetic:
geometric patterns carrying metadata this project wrote itself. That proves the plugin
handles *well-formed* metadata. It cannot prove the plugin handles what DALL·E, Firefly,
Midjourney, ComfyUI or a Pixel phone actually emit.

The gap is not theoretical. Test case 11 was written expecting `ai_generated` and
returned `unknown`: Pillow writes EXIF `UserComment` as type BYTE while the spec says
UNDEFINED, and the detector accepted only the spec type. 340 passing tests had missed
it, because every hand-built fixture used the conformant type. One piece of real encoder
output found it immediately.

So: if you have an image whose provenance this reads wrongly — or fails to read at all —
that is a more valuable contribution than a patch. Open an issue and attach it.

## Setup

```bash
python -m venv .venv && .venv/bin/pip install -e '.[dev,thumbor]'
```

```bash
.venv/bin/python -m pytest --cov=thumbor_ai_label --cov-report=term-missing
```

CI runs the suite on Python 3.10 through 3.14 with `--cov-fail-under=100`. **Coverage is
enforced, not aspirational.** If a line cannot be reached by a test, that is usually a
sign the line should not exist — several defensive branches were deleted during
development for exactly that reason.

## Things that are easy to get wrong here

**Generated files are generated.** Do not hand-edit these; change the generator and
re-run it:

| Files | Generator |
|---|---|
| `src/thumbor_ai_label/icons/*.png` | `tools/make_icons.py` |
| `src/thumbor_ai_label/icons/eu*/` | `tools/fetch_eu_icons.py` |
| `tests/images/` and its manifest | `tools/make_test_images.py` |

**`scan/` and `detect/` must not import Thumbor.** They are deliberately standalone so
they can be tested and reused without Thumbor's dependency pins. Only `engine.py`,
`handler.py`, `app.py`, `config.py`, `meta.py` and `filters/` may import it.

**The scanner must never raise.** It parses untrusted bytes inside a request path. A
corrupt or hostile file yields a partial result with `truncated` set and an explanatory
note — never an exception, because that would turn a weird image into a 500. The suite
fuzzes ~10,500 mutated inputs asserting exactly this.

**Broad `except Exception` is often deliberate here**, not sloppiness. Labelling must not
take image delivery down. Where you see one, there should be a comment saying what it is
containing and why; add that comment if you add such a handler.

**`unknown` is not an AI claim.** The plugin distinguishes "we know this is AI" from "we
could not establish provenance". Do not collapse them, do not use an official EU mark for
`unknown`, and do not phrase its disclosure as though the image were AI. Someone relying
on a screen reader cannot check for themselves.

## Adding a detector

Detectors are resolved from an entry point group, so you can ship one from your own
package without touching this repository:

```toml
[project.entry-points."thumbor_ai_label.detectors"]
my_detector = "my_package.detectors:provenance"
```

A detector is any module or object exposing `NAME`, `REQUIRES` and `detect`. `detect`
may be sync or async — async if it needs to call another system, such as a DAM lookup.
It returns a `Detection` or `None`.

Detectors that belong in this repository are ones covering a public standard. A lookup
against your own internal system belongs in your own package.

## Reporting a bug

Attach the image if you can. A provenance bug is almost impossible to act on without the
bytes that triggered it, and a description of the metadata is not a substitute — the
`UserComment` bug above would have been invisible from any description of it.
