# Test image corpus

24 images for validating the plugin against a running Thumbor, plus
[`manifest.json`](manifest.json) recording what each should produce.

## These images are synthetic

They are geometric patterns carrying hand-written provenance metadata — **not** output
from any AI system. A file whose EXIF reads `Midjourney` was not made by Midjourney; it
exists to prove the parser reads that tag.

**That is also the limitation.** This corpus proves the plugin handles *well-formed*
metadata that this project wrote itself. It cannot prove the plugin handles what real
generators actually emit. Only real files from DALL·E, Firefly, Midjourney, Pixel and
the rest can do that, and contributing some is the most useful thing you can do for
this project.

It is not a hypothetical gap. Case 11 was written expecting `ai_generated` and returned
`unknown`: Pillow writes EXIF `UserComment` as type BYTE while the spec says UNDEFINED,
and the detector only accepted the spec type. 340 passing unit tests had missed it,
because every hand-built fixture used the conformant type. One encoder's real output
found it immediately.

## Using them

Point a Thumbor file loader at this directory:

```python
LOADER = "thumbor.loaders.file_loader"
FILE_LOADER_ROOT_PATH = "/path/to/testdata"
```

Then request any of them, e.g. `/unsafe/600x400/01-iptc-ai-generated.jpg`.

Each image is captioned top-left with what it expects, so you can judge a rendered
result at a glance. The caption sits opposite the default label corner and cannot
collide with it.

## Checking automatically

```bash
python tools/verify_test_images.py
```

Runs every image under both policies and compares against the manifest. Exits non-zero
on mismatch, so it doubles as a smoke test after a config change or Thumbor upgrade.

```bash
python tools/render_test_images.py --icon-set eu --policy strict --width 380
```

Builds a contact sheet showing the labels actually drawn. The manifest checks the
*decision*; only a picture shows legibility, placement, and that case 21 correctly
carries no label.

## What each case covers

| # | Case | Strict | Relaxed |
|---|---|---|---|
| 01–03 | IPTC generated / composite / modified | labelled | labelled |
| 04–06 | IPTC camera, digital art, composite capture | no label | no label |
| 07 | IPTC term this build does not know | unknown | unknown |
| 08 | Bare term, no CV URI | ai_generated | ai_generated |
| 09 | EXIF Software names a generator | ai_generated | ai_generated |
| 10 | **EXIF Software is plain Photoshop** | unknown | no label |
| 11 | Generation params in EXIF UserComment | ai_generated | ai_generated |
| 12 | No metadata at all | unknown | no label |
| 13 | **EXIF camera tags only, no XMP** | unknown | **no label** |
| 14 | XMP present, no DigitalSourceType | unknown | **unknown** |
| 15–17 | PNG iTXt, WebP, PNG ImageMagick raw profile | ai_generated | ai_generated |
| 18 | XMP says camera, EXIF says Midjourney | no label | no label |
| 19 | Extended XMP split across segments | ai_generated | ai_generated |
| 20 | Truncated, unparseable XMP | unknown | unknown |
| 21 | AI image 140×80 | detected, **no label drawn** | same |
| 22–24 | Panorama, tall portrait, dark image | ai_generated | ai_generated |

### The three worth studying

**10** is the precision check. Most images that pass through Photoshop are not AI, so a
match here would label real photographs. It must stay silent.

**13 vs 14** is the whole difference between the policies. Both carry metadata, but only
14 carries a *provenance-capable* block. EXIF defines no provenance field, so 13 asserts
nothing either way — and counting it would label essentially every camera photograph
ever taken. Look at these two before choosing `AI_LABEL_POLICY`.

**21** is detected as `ai_generated` but draws nothing: its shorter edge is under
`AI_LABEL_MIN_IMAGE_SIZE`. Detection and drawing are separate decisions, and the
manifest only records the first.

## Regenerating

```bash
python tools/make_test_images.py
```
