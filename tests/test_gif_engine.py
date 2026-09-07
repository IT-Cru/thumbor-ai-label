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
  leaves ``/meta/`` reporting ``detection_disabled`` for an image the plugin was
  fully enabled for and did scan.

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
from tests.builders import gif
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


class TestAGifGetsAnHonestVerdict(GifOverHttp):
    """A GIF is examined, and /meta/ says so - even though no filter ever runs for it.

    `BaseHandler.after_transform` guards `apply_filters(PHASE_POST_TRANSFORM)` with
    `extension != ".gif" or USE_GIFSICLE_ENGINE is None`. `USE_GIFSICLE_ENGINE`
    defaults to `False`, not `None`, so for **any** GIF on **any** engine the guard is
    false and no post-transform filter runs - `ai_label` included.

    The verdict is therefore computed in `AiLabelImagingHandler.after_transform`,
    before `super()` finishes the request. Until #24 that ran *after* `super()`, which
    ends in `finish_request()`, so the payload was already built and GIFs reported
    `detection_disabled` - claiming the plugin was switched off for an image it had in
    fact scanned.
    """

    def verdict(self, image="ai.gif"):
        import json

        response = self.fetch(f"/unsafe/meta/160x120/{image}")
        assert response.code == 200, response.body[:200]
        return json.loads(response.body)["ai_label"]

    def test_the_scan_is_reported_as_inconclusive_not_disabled(self):
        """Examined and nothing found - not "never examined".

        `detection_disabled` told a CMS a gap in coverage was a configuration
        choice. Under the strict default an unreadable image reaches `unknown`,
        which is this plugin's fail-closed hedge and the honest answer here.
        """
        verdict = self.verdict()
        assert verdict["reason"] == "inconclusive"
        assert verdict["label"] == "unknown"

    def test_a_disclosure_is_offered_so_the_cms_can_write_one(self):
        """The DOM disclosure is the only one a GIF carries, so it must be there."""
        assert "could not be established" in self.verdict()["disclosure"]

    def test_labelled_is_false_because_nothing_was_drawn(self):
        """True for the reason #19 established, on the engine this case runs on."""
        assert self.verdict()["labelled"] is False

    def test_an_animated_gif_reports_the_same(self):
        assert self.verdict("animated.gif")["reason"] == "inconclusive"

    def test_the_verdict_is_still_empty_because_the_scan_is(self):
        """`unknown`, not `ai_generated`, though the GIF does carry the assertion.

        The scanner has no GIF walker (#25), so the XMP in these fixtures is never
        read. Fixing that should turn this into `ai_generated` and break this test,
        which is the point of asserting it.
        """
        assert self.verdict()["label"] != "ai_generated"
