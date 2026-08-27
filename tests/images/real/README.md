# Contributed images

Real output from real AI tools. **Nothing here is generated** — every file was produced
by a third-party tool and donated, and must never be rewritten.

That is the opposite of the directory above, which `tools/make_test_images.py` owns and
regenerates byte-identically. See [../README.md](../README.md) for why they are separate.

The corpus is currently empty. See issue #2 — contributions are wanted, and this is the
most useful thing anyone can give this project.

## Adding one

1. **Check what the file carries** before you attach it anywhere:

   ```bash
   exiftool -a -G1 yourfile.jpg
   ```

   EXIF routinely holds GPS coordinates, creator names and camera serial numbers.
   Generation parameters hold the prompt you typed. This repository is public and
   permanent; anything merged cannot meaningfully be unpublished. Prefer generating
   something new for this purpose over donating an image you already had.

2. **Do not scrub the metadata.** Stripping GPS changes the bytes under test, which is the
   whole reason the file is valuable. Either it is safe to publish as-is, or it is not a
   candidate. Never quietly modify a contributed file.

3. **Add the file and a manifest entry:**

   ```json
   {
     "file": "dalle3-mountain-landscape.jpg",
     "description": "DALL-E 3 output, downloaded directly, metadata untouched",
     "source": "OpenAI DALL-E 3",
     "expected": { "strict": "ai_generated", "relaxed": "ai_generated" },
     "contributed_in": "#42",
     "notes": "Carries a C2PA manifest as well as IPTC DigitalSourceType."
   }
   ```

   | Field | Meaning |
   |---|---|
   | `file` | Filename in this directory |
   | `description` | What it is and how it was obtained |
   | `source` | The tool that produced it, with a version if you know it |
   | `expected.strict` / `expected.relaxed` | The `label` value each policy should return, or `null` for no label |
   | `contributed_in` | The PR that added it — where the licensing statement lives |
   | `notes` | Anything a maintainer would otherwise have to rediscover |

4. **Run the suite.** `pytest tests/test_corpus.py -v` will report a mismatch between what
   you expected and what the plugin actually does.

## If the plugin gets it wrong

That is the point. A file the plugin misreads is worth more than one it handles, because
it is evidence of a real bug rather than a passing test. Record what you expected in the
manifest, open the PR anyway, and say so — a failing case with a clear expectation is a
better bug report than any description.

## When an expectation legitimately changes

If a detector improves and a file starts returning something different, that is a fix, not
a regression. Update `expected` **and** say why in `notes`, so the edit does not read as
someone weakening a test to make CI pass.
