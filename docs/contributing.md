# Contributing

The full guide lives in
[CONTRIBUTING.md](https://github.com/IT-Cru/thumbor-ai-label/blob/main/CONTRIBUTING.md)
in the repository, so it is next to the code it describes and visible to anyone opening a
pull request. This page only summarises it.

## The most useful contribution is not a patch

**It is a real image from a real AI tool** whose provenance this plugin reads wrongly, or
fails to read at all.

Every fixture in the test suite is synthetic — geometric patterns carrying metadata this
project wrote itself. That proves the parsers handle *well-formed* input. It cannot prove
they handle what DALL·E, Firefly, Midjourney or a Pixel phone actually emit.

That gap is not hypothetical. One test case was written expecting `ai_generated` and
returned `unknown`: Pillow writes EXIF `UserComment` as type `BYTE` while the
specification says `UNDEFINED`, and the detector accepted only the specification type.
340 passing tests had missed it. The first contact with real encoder output found it
immediately.

!!! warning "Check what the file carries before attaching it"
    EXIF routinely holds GPS coordinates, creator names and camera serial numbers.
    Generation parameters hold the prompt you typed. Repositories are public and
    permanent. Run `exiftool -a -G1 yourfile.jpg` first, and prefer generating something
    new for the purpose over donating an image you already had.

[Issue #2 tracks the ask →](https://github.com/IT-Cru/thumbor-ai-label/issues/2)

## Licensing

Contributions are Apache-2.0 by submission, under Apache-2.0 §5. You keep the copyright in
your own contribution and there is no CLA to sign.

## Reporting a vulnerability

Privately, through the repository's Security tab — see
[SECURITY.md](https://github.com/IT-Cru/thumbor-ai-label/blob/main/SECURITY.md). This
plugin parses untrusted bytes inside a request path, so a crafted image that crashes,
hangs or exhausts memory is a security report rather than an ordinary bug.
