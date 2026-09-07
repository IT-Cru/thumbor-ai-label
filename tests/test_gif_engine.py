"""The GIF round trip, driven through the real ``gifsicle`` binary.

``thumbor.engines.gif.Engine`` shells out to ``gifsicle`` for every operation -
``load`` alone runs ``--info`` before it returns - so nothing in this module works
without the binary and the whole file skips when it is absent. CI installs it; see
CONTRIBUTING.md.

#17 wrapped the ``GIF_ENGINE`` slot so GIFs are scanned as well, and shipped in
v0.3.0 with the round trip asserted only as far as the wrapping. Closing that is
what this module is for, and what it turns up is worth stating plainly:

* the engine hook does reach a GIF, and a scan is stored;
* the scan is **empty**, because the container scanner has no GIF walker;
* the label filter never runs for a GIF at all, so no verdict is computed - which
  makes ``/meta/`` report ``detection_disabled`` for an image detection was very
  much enabled for.

The last two are defects with their own issues. Tests here pin what happens today
so a fix cannot land unnoticed.
"""

from __future__ import annotations

import io
import pathlib
import shutil
import tempfile
from typing import ClassVar

import pytest

pytest.importorskip("thumbor", reason="the Thumbor layer needs Thumbor installed")

from PIL import Image
from thumbor.config import Config
from thumbor.context import Context, ServerParameters
from thumbor.importer import Importer
from tornado.testing import AsyncHTTPTestCase

import thumbor_ai_label.config  # noqa: F401 - imported for the side effect of registering config keys
from thumbor_ai_label.app import AiLabelServiceApp
from thumbor_ai_label.engine import AiLabelEngineMixin
from thumbor_ai_label.state import get_scan

GIFSICLE = shutil.which("gifsicle")

#: Not a skip on individual tests: without the binary the gif engine cannot even
#: load, so every assertion in the file is unreachable rather than merely awkward.
pytestmark = pytest.mark.skipif(
    GIFSICLE is None,
    reason="the gifsicle engine shells out to the gifsicle binary for every operation",
)

CV = "http://cv.iptc.org/newscodes/digitalsourcetype/"
NS = 'xmlns:Iptc4xmpExt="http://iptc.org/std/Iptc4xmpExt/2008-02-29/"'

#: XMP's GIF serialisation (XMP spec part 3): an Application Extension labelled
#: "XMP DataXMP", the packet, then a 258-byte magic trailer of descending bytes
#: that lets a GIF reader walk the packet as though it were sub-blocks.
XMP_APP_LABEL = b"\x21\xff\x0bXMP DataXMP"
XMP_MAGIC_TRAILER = bytes(range(255, -1, -1)) + b"\x00"
GIF_TRAILER = b"\x3b"


def gif(term: str | None = None, frames: int = 1, size=(240, 180)) -> bytes:
    """A GIF89a, optionally carrying a DigitalSourceType assertion in XMP."""
    images = [
        Image.new("RGB", size, (40 + 50 * index, 110, 160)).convert("P") for index in range(frames)
    ]
    buf = io.BytesIO()
    images[0].save(buf, "GIF", save_all=True, append_images=images[1:], duration=120, loop=0)
    raw = buf.getvalue()

    if term is None:
        return raw

    xmp = (
        '<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF><rdf:Description '
        f'{NS} Iptc4xmpExt:DigitalSourceType="{CV}{term}"/></rdf:RDF></x:xmpmeta>'
    ).encode()
    assert raw.endswith(GIF_TRAILER)
    return raw[: -len(GIF_TRAILER)] + XMP_APP_LABEL + xmp + XMP_MAGIC_TRAILER + GIF_TRAILER


def build_context(**overrides) -> Context:
    """A context whose gif engine can actually run.

    `ServerParameters` carries the binary path, not config: `thumbor.engines.gif`
    reads `context.server.gifsicle_path`, and `thumbor.server.validate_config` is
    what normally fills it in with `which("gifsicle")`. A test that builds
    `ServerParameters` itself gets `None` and has to say so.
    """
    config = Config(SECURITY_KEY="test-key", USE_GIFSICLE_ENGINE=True, **overrides)
    importer = Importer(config)
    importer.import_modules()
    server = ServerParameters(
        8888, "localhost", "thumbor.conf", None, "info", None, gifsicle_path=GIFSICLE
    )
    boot = Context(server=server, config=config, importer=importer)
    AiLabelServiceApp._install_engine_hook(boot)
    # Exactly how ContextHandler.initialize builds a request's context.
    return Context(server=server, config=config, importer=boot.modules.importer)


class TestTheHookReachesAGif:
    """The half of #17 that shipped untested: a GIF really does get scanned."""

    def load(self, raw: bytes):
        context = build_context()
        engine = context.modules.gif_engine
        engine.load(raw, ".gif")
        return context, engine

    def test_the_gif_engine_instance_carries_the_mixin(self):
        context = build_context()
        assert isinstance(context.modules.gif_engine, AiLabelEngineMixin)

    def test_loading_a_gif_stores_a_scan(self):
        """`gif.Engine.load` never calls `super().load`, so this is not a given.

        It overrides `load` outright. Our mixin sits ahead of it in the MRO and
        calls down, which is why the scan still happens - and why it is worth
        asserting against the real class rather than reasoning about it.
        """
        context, _ = self.load(gif(term="trainedAlgorithmicMedia"))
        assert get_scan(context) is not None

    def test_gifsicle_really_ran(self):
        """`load` calls `--info` through the binary to fill in size and frame count."""
        _, engine = self.load(gif(frames=3))
        assert engine.size == [240, 180]
        assert engine.frame_count == 3

    def test_the_engine_holds_no_pil_image(self):
        """The premise of #19, confirmed against the real engine rather than a stub."""
        from thumbor_ai_label.compose import can_draw_on

        _, engine = self.load(gif())
        assert engine.image == ""
        assert can_draw_on(engine) is False


class TestTheScanIsEmptyBecauseGifIsUnsupported:
    """A GIF is scanned, and nothing comes back: the scanner has no GIF walker.

    `scan.sniff` knows JPEG, PNG and WebP. A GIF89a carrying a perfectly valid XMP
    packet yields `container=None` and one note, so no detector can ever fire on a
    GIF however it was generated.

    Pinned here rather than left implicit: adding a GIF walker should break this
    test and make its author decide what the new behaviour is.
    """

    def test_a_gif_carrying_xmp_scans_to_nothing(self):
        context = build_context()
        context.modules.gif_engine.load(gif(term="trainedAlgorithmicMedia"), ".gif")

        result = get_scan(context)
        assert result.container is None
        assert result.segments == []
        assert "unrecognised container" in result.notes

    def test_the_xmp_really_is_in_the_bytes(self):
        """Otherwise the test above would pass for the wrong reason."""
        assert b"DigitalSourceType" in gif(term="trainedAlgorithmicMedia")


class GifOverHttp(AsyncHTTPTestCase):
    extra_config: ClassVar[dict] = {}

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        root = pathlib.Path(cls._tmp.name)
        (root / "ai.gif").write_bytes(gif(term="trainedAlgorithmicMedia"))
        (root / "animated.gif").write_bytes(gif(term="trainedAlgorithmicMedia", frames=4))
        cls.root = root

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def get_app(self):
        settings = {
            "SECURITY_KEY": "test-key",
            "ALLOW_UNSAFE_URL": True,
            "USE_GIFSICLE_ENGINE": True,
            "ALLOW_ANIMATED_GIFS": True,
            "LOADER": "thumbor.loaders.file_loader",
            "FILE_LOADER_ROOT_PATH": str(self.root),
            "STORAGE": "thumbor.storages.no_storage",
            "RESULT_STORAGE": "thumbor.result_storages.no_storage",
        }
        settings.update(self.extra_config)
        config = Config(**settings)
        importer = Importer(config)
        importer.import_modules()
        server = ServerParameters(
            8888, "localhost", "thumbor.conf", None, "info", None, gifsicle_path=GIFSICLE
        )
        return AiLabelServiceApp(Context(server=server, config=config, importer=importer))


class TestGifsAreStillDelivered(GifOverHttp):
    """Whatever the plugin cannot do to a GIF, it must not break serving one."""

    def test_a_gif_is_resized_and_served(self):
        response = self.fetch("/unsafe/160x120/ai.gif")
        assert response.code == 200, response.body[:200]
        assert response.body.startswith(b"GIF89a"), "gifsicle produced the output"
        assert Image.open(io.BytesIO(response.body)).size == (160, 120)

    def test_an_animated_gif_is_served_with_its_frames(self):
        """#19 flagged a possible failure inside `frame_engines()`. There is none.

        `gif.Engine.is_multiple()` is `frame_count > 1` while `multiple_engine` is
        only ever set on the PIL path, so `BaseFilter.run` looked like it would
        break on a multi-frame GIF. It does not - post-transform filters never run
        for a GIF at all, so nothing reaches `frame_engines()`.
        """
        response = self.fetch("/unsafe/160x120/animated.gif")
        assert response.code == 200, response.body[:200]
        assert Image.open(io.BytesIO(response.body)).n_frames == 4


class TestNoVerdictIsComputedForAGif(GifOverHttp):
    """Thumbor skips the whole post-transform phase for GIFs, so the filter never runs.

    `BaseHandler.after_transform` guards `apply_filters(PHASE_POST_TRANSFORM)` with
    `extension != ".gif" or USE_GIFSICLE_ENGINE is None`. `USE_GIFSICLE_ENGINE`
    defaults to `False`, not `None`, so for **any** GIF on **any** engine the guard
    is false and no post-transform filter runs - including `ai_label`.

    So no verdict is computed, and `/meta/` falls back to `detection_disabled`. That
    is wrong: detection is enabled and the scan ran. Pinned as current behaviour
    with the honest verdict marked xfail below.
    """

    def verdict(self, image="ai.gif"):
        import json

        response = self.fetch(f"/unsafe/meta/160x120/{image}")
        assert response.code == 200, response.body[:200]
        return json.loads(response.body)["ai_label"]

    def test_the_payload_is_still_published(self):
        assert self.verdict()["policy"] == "strict"

    def test_it_reports_detection_disabled_today(self):
        verdict = self.verdict()
        assert verdict["label"] is None
        assert verdict["reason"] == "detection_disabled"

    @pytest.mark.xfail(
        strict=True,
        reason="the label filter never runs for a GIF, so no verdict is computed",
    )
    def test_it_should_report_that_the_scan_found_nothing(self):
        """What the payload ought to say once a verdict is computed for GIFs.

        `inconclusive` under the strict default: the image was examined and no
        provenance was found. `detection_disabled` claims it was never examined,
        which tells a CMS the opposite of the truth about its own coverage.
        """
        assert self.verdict()["reason"] == "inconclusive"
