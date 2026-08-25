# Security policy

## Reporting a vulnerability

**Please report privately, not in a public issue.**

Use GitHub's private vulnerability reporting: the **Security** tab → **Report a
vulnerability**. That opens a private advisory visible only to the maintainers.

Include the image that triggers it if you have one. This plugin's whole job is parsing
bytes other people control, and a description of a malformed file is rarely enough to
reproduce from — the bytes are the report.

This is a small project with no funded security team. Reports are handled on a best-effort
basis; there is no response-time guarantee. Coordinated disclosure is appreciated, and
credit will be given in the advisory unless you would rather not be named.

## Supported versions

Pre-1.0: only the latest release is supported. There are no backports.

## Where the risk actually is

The plugin parses **untrusted bytes inside a request path**. Anything reachable from a
crafted source image is the interesting surface:

| Component | Handles |
|---|---|
| `scan/` | JPEG marker chains, PNG chunks, RIFF chunks, zlib-compressed text |
| `detect/iptc` | XMP packets (XML-shaped text, arbitrary encodings) |
| `detect/exif` | TIFF IFD structures, offsets and nested sub-IFDs |
| `meta` | Serialising the verdict into a publicly reachable JSON response |

### Properties the code is meant to hold

A report is most useful when it shows one of these being violated:

- **The scanner never raises.** Corrupt or hostile input must yield a partial result with
  `truncated` set, never an exception — an exception here becomes a 500. The suite fuzzes
  around 10,500 mutated and truncated inputs asserting this.
- **All parsing is bounds-checked and budgeted.** Fixed limits, not currently
  configurable: 256 segments per image; 2 MiB XMP; 1 MiB EXIF; 8 MiB JUMBF; 16 KiB per
  EXIF value; 512 IFD entries per directory. The Exif sub-IFD pointer is followed exactly
  once, so a pointer loop cannot spin.
- **No XML parser touches untrusted input.** The IPTC detector locates
  `DigitalSourceType` by targeted scan precisely to avoid entity-expansion and
  external-entity attacks. A test asserts a billion-laughs payload is inert. Introducing
  an XML parser here would be a regression, not an improvement.
- **Decompression is capped.** PNG `iTXt`/`zTXt` inflation is bounded, so a compression
  bomb is cut off rather than honoured.
- **Cost does not scale with image size.** The scan reads metadata, never image data. A
  crafted file that makes scan time grow with file size is a denial-of-service report.
- **Payloads stay out of logs.** `RawSegment.__repr__` omits the bytes it holds, because
  metadata can carry GPS coordinates, creator names and camera serials.

## Not security issues

These are worth reporting — some of them very much so — but as ordinary bugs:

- **An AI image was not labelled.** A detection gap is a correctness bug and a welcome
  one (see [CONTRIBUTING.md](CONTRIBUTING.md); real-world samples are the most useful
  contribution to this project). It is not a vulnerability.
- **Stripping the metadata removed the label.** Working as designed. The plugin reads
  what the file declares; it cannot detect AI from pixels and does not claim to.
- **The label can be cropped, or the image re-hosted without it.** Out of scope. Thumbor
  draws the label; what happens to the image afterwards is outside this plugin's control.
- **`unknown` appears on ordinary photographs.** That is the documented behaviour of the
  default `strict` policy. See the README on `AI_LABEL_POLICY`.

## Hardening a deployment

- **Keep `AI_LABEL_META_VERBOSE = False`** — the default. When enabled, the `/meta/`
  endpoint includes an `evidence` field that can carry a fragment of a generation prompt
  read out of EXIF `UserComment`. That endpoint is publicly reachable, and the field is
  capped at 120 characters but not otherwise sanitised.
- **Consider `AI_LABEL_META = False`** if you do not consume the endpoint. It reveals
  which of your images carry AI provenance, which you may not wish to publish.
- **Leave `AI_LABEL_STRICT_ERRORS = False`** unless you would genuinely rather serve
  nothing than serve an unlabelled image. It turns a bad icon path into a failed request.
- **Restrict your loader.** The most effective control is not in this plugin: an
  unrestricted Thumbor loader lets anyone feed arbitrary bytes to every parser in the
  stack, this one included.
