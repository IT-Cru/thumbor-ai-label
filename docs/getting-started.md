# Getting started

## Requirements

- **Thumbor 7.8+** and **Python 3.10+**
- Source images in **JPEG, PNG or WebP**. AVIF and HEIC are not yet supported.
- Any engine. The plugin subclasses whichever one you have configured.

```bash
pip install thumbor-ai-label
```

## Minimal configuration

One key in `thumbor.conf` is the whole integration:

```python
# Labels every image, with no change to any URL.
APP_CLASS = "thumbor_ai_label.app.AiLabelServiceApp"
```

`APP_CLASS` does two things: it arranges for every request to be labelled, and it installs
the hook that reads the original bytes. `engine.load()` is the only point in Thumbor's flow
that always receives the source file — on both the storage-hit and loader paths — so the
app subclasses whichever engine you have configured, at startup, and logs what it wrapped:

```
[AiLabel] engine hook installed on thumbor.engines.pil.Engine, thumbor.engines.gif.Engine
```

## Running a different engine

Nothing to do. Leave `ENGINE` pointing at your engine and the app composes with it:

```python
ENGINE = "my.engine"
APP_CLASS = "thumbor_ai_label.app.AiLabelServiceApp"
```

Both engine slots are covered, so `GIF_ENGINE` is hooked too when
`USE_GIFSICLE_ENGINE` is on.

!!! note "Upgrading from v0.2.0 or earlier"
    Those versions required `ENGINE = "thumbor_ai_label.engine"`, which meant the plugin
    could not coexist with another custom engine. That line still works and can stay —
    the app skips a slot that already carries the hook — but it is no longer needed, and
    removing it is what frees the slot for your own engine.

## Opt-in per URL instead

If you would rather label selectively, skip `APP_CLASS`, add the filter to `FILTERS`, and
put `ai_label()` in the URLs that should carry a label:

```python
FILTERS = ["thumbor_ai_label.filters.ai_label"]
ENGINE = "thumbor_ai_label.engine"
```

`ENGINE` **is** required here. Without `APP_CLASS` there is no app to install the hook, so
this is the one setup that still names the engine explicitly. Running your own engine as
well means subclassing it yourself:

```python
from thumbor_ai_label.engine import AiLabelEngineMixin
from my.engine import Engine as Base

class Engine(AiLabelEngineMixin, Base):
    pass
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
