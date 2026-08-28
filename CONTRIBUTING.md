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

The European Commission icons under `ai-labels/eu/` and `ai-labels/eu-white/` are
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
that is a more valuable contribution than a patch.

Contributed files live in [`tests/images/real/`](tests/images/real/), which has its own
README covering what to check before attaching anything — real images carry GPS
coordinates, creator names, and the prompt you typed, and this repository is public and
permanent. Issue #2 tracks the ask.

## Setup

```bash
python -m venv .venv && .venv/bin/pip install -e '.[dev,thumbor]'
.venv/bin/pre-commit install
```

`pre-commit install` is worth the ten seconds: it runs the lint and format gates before
each commit rather than after, in CI. CI runs `pre-commit run --all-files`, so the ruff
version pinned in `.pre-commit-config.yaml` is the single source of truth — your machine
and CI cannot disagree.

```bash
.venv/bin/python -m pytest --cov=thumbor_ai_label --cov-report=term-missing
```

```bash
.venv/bin/pre-commit run --all-files
```

CI runs that, plus the suite on Python 3.10 through 3.14 with `--cov-fail-under=100`.
**Both are enforced, not aspirational.** If a line cannot be reached by a test, that is
usually a sign the line should not exist — several defensive code paths were deleted
during development for exactly that reason.

Formatting is `ruff format` with the default style at a 100-column limit. Do not hand-
tune layout — run the formatter and take what it gives you. That is the point of having
one: layout stops being a thing anybody argues about in review.

Two things that catch people out:

- **`ruff format .` rewrites Python code blocks inside Markdown, but CI does not check
  them.** The `ruff-format` hook declares `types_or: [python, pyi, jupyter]`, so Markdown
  never reaches it and a documented example's layout cannot fail CI. Matching the
  formatter's style in examples is still the house convention — just know that running
  the formatter across the whole tree silently rewrites prose files nothing is gating,
  so prefer `ruff format src tests tools`.
- **`ruff check` and `ruff format --check` are separate gates.** Passing the first says
  nothing about the second. Running pre-commit covers both, which is the reason to
  install it.

## Branch naming

Branches follow [Conventional Branch](https://conventionalbranch.org/) v1.1.0:
`<type>/<description>`.

| Prefix | For |
|---|---|
| `feature/` or `feat/` | new features |
| `bugfix/` or `fix/` | bug fixes |
| `hotfix/` | urgent fixes |
| `release/` | preparing a release |
| `chore/` | non-code tasks — dependencies, docs, tooling |

Lowercase `a-z`, digits and hyphens only — no underscores, spaces or other punctuation,
and no leading, trailing or consecutive hyphens. Dots are allowed only in a `release/`
description, for the version number. Trunk branches (`main`) carry no prefix.

Include the issue number where there is one:

```text
feature/issue-9-icon-sets
fix/issue-42-webp-truncation
chore/issue-1-mkdocs-site
```

Choose the prefix from what the change does to the *shipped plugin*, not from the size of
the diff. Moving files around is `chore/`. Moving files around **and** adding a config
value people can set is `feature/`, because the second half is the part they notice.

**Do not use the AI agent source prefixes.** v1.1.0 adds `ai/`, `claude/`, `codex/`,
`copilot/` and `cursor/` for branches an agent produced. This project does not use them.
A branch name should say what the work *is*, so it still means something in a branch
listing months later; which tool typed it is neither durable nor relevant to reviewing
the diff. Authorship belongs in commit trailers, where `Co-Authored-By` already records
it.

## Things that are easy to get wrong here

**Generated files are generated.** Do not hand-edit these; change the generator and
re-run it:

| Files | Generator |
|---|---|
| `ai-labels/default/`, `ai-labels/default-light/` | `tools/make_icons.py` |
| `ai-labels/eu/`, `ai-labels/eu-white/` | `tools/fetch_eu_icons.py` |
| `tests/images/` — the numbered images and `manifest.json` | `tools/make_test_images.py` |

`unknown.png` inside `ai-labels/eu/` and `ai-labels/eu-white/` is written by
`fetch_eu_icons.py` but *drawn* by `make_icons.py`: the EU sets borrow this plugin's own
neutral mark rather than an official one. Change the artwork with `make_icons.py`, then
re-run `fetch_eu_icons.py` to copy it across.

**`tests/images/real/` is not generated** and is not covered by the row above: those are
contributed files from real AI tools. Editing one destroys the only reason it exists.

**`scan/` and `detect/` must not import Thumbor.** They are deliberately standalone so
they can be tested and reused without Thumbor's dependency pins. Only `engine.py`,
`handler.py`, `app.py`, `config.py`, `meta.py` and `filters/` may import it.

**The scanner must never raise.** It parses untrusted bytes inside a request path. A
corrupt or hostile file yields a partial result with `truncated` set and an explanatory
note — never an exception, because that would turn a weird image into a 500. The suite
fuzzes ~10,500 mutated inputs asserting exactly this.

**Broad `except Exception` is deliberate here**, not sloppiness. Labelling must not take
image delivery down, and the scanner must never raise on hostile input. Ruff's `BLE001`
is switched **on** rather than off for exactly this reason: every such site needs an
explicit `# noqa: BLE001` plus a reason, so a careless broad except cannot slip in
disguised as a deliberate one. If you add one, justify it or ruff will stop you.

The lint rule set is pinned explicitly in `pyproject.toml` rather than inherited from
ruff's defaults, which shift between releases — otherwise upgrading ruff would turn into
a surprise CI failure.

One trap worth knowing: never run `ruff check --fix` with a partial `--select`. Ruff
treats any `# noqa` for a rule outside that selection as dead and strips it, quietly
removing suppressions the full configuration still needs. Run a bare `ruff check --fix`,
which reads the configured set.

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

Found something with security implications — a crafted image that crashes the parser,
hangs it, or exhausts memory? Report it privately instead: see [SECURITY.md](SECURITY.md).


Attach the image if you can. A provenance bug is almost impossible to act on without the
bytes that triggered it, and a description of the metadata is not a substitute — the
`UserComment` bug above would have been invisible from any description of it.
