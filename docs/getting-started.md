# Getting started

## Requirements

- **Thumbor 7.8+** and **Python 3.10+**
- Source images in **JPEG, PNG or WebP**. AVIF and HEIC are not yet supported.
- The bundled engine wraps Thumbor's PIL engine

```bash
pip install thumbor-ai-label
```

## Minimal configuration

Two keys in `thumbor.conf` are the whole integration:

```python
# Labels every image, with no change to any URL.
APP_CLASS = "thumbor_ai_label.app.AiLabelServiceApp"

# The engine hook is what sees the original bytes; without it nothing is detected.
ENGINE = "thumbor_ai_label.engine"
```

!!! warning "Both keys are required"
    `APP_CLASS` arranges for every request to be labelled. `ENGINE` is what actually sees
    the original file — `engine.load()` is the only point in Thumbor's flow that always
    receives the source bytes, on both the storage-hit and loader paths.

    Set `APP_CLASS` without `ENGINE` and images are served normally, unlabelled, with a
    warning in the log. That fails safe, but it fails silently to anyone not reading logs.

## Running a different engine

Compose your own rather than replacing it:

```python
from thumbor_ai_label.engine import AiLabelEngineMixin
from my.engine import Engine as Base

class Engine(AiLabelEngineMixin, Base):
    pass
```

## Opt-in per URL instead

If you would rather label selectively, skip `APP_CLASS`, add the filter to `FILTERS`, and
put `ai_label()` in the URLs that should carry a label:

```python
FILTERS = ["thumbor_ai_label.filters.ai_label"]
```

The trade is that every URL-generating system has to be updated, and a URL that forgets it
is silently unlabelled. Always-on has no such failure mode, which is why it is the
documented default.

## Verifying it works

The repository ships
[24 test images](https://github.com/IT-Cru/thumbor-ai-label/tree/main/tests/images)
covering every detection and policy case, with a manifest of expected outcomes. Point a
file loader at them:

```python
LOADER = "thumbor.loaders.file_loader"
FILE_LOADER_ROOT_PATH = "/path/to/thumbor-ai-label/tests/images"
```

Then request a few:

```
/unsafe/600x400/01-iptc-ai-generated.jpg     labelled
/unsafe/600x400/04-iptc-camera.jpg           not labelled
/unsafe/meta/600x400/01-iptc-ai-generated.jpg   the verdict as JSON
```

Each image is captioned top-left with what it expects, opposite the label corner so the
two cannot collide.

## What to decide next

The one configuration choice that materially changes what your users see is
`AI_LABEL_POLICY`. Under the default, images whose provenance cannot be established are
labelled `unknown` — which on older content means most of them.

[Read about policy, and how to measure it against your own images →](configuration.md#policy)
