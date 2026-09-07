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
from thumbor_ai_label.scan import Container
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


class TestTheScanReadsGifProvenance:
    """A GIF is scanned like any other container now that a walker exists.

    Until #25 `scan.sniff` knew JPEG, PNG and WebP only, so a GIF89a carrying a
    perfectly valid XMP packet yielded `container=None` and one note - no detector
    could fire on a GIF however it was generated.
    """

    def scan_of(self, raw: bytes):
        context = build_context()
        context.modules.gif_engine.load(raw, ".gif")
        return get_scan(context)

    def test_the_xmp_packet_is_lifted_out(self):
        result = self.scan_of(gif(term="trainedAlgorithmicMedia"))

        assert result.container is Container.GIF
        assert result.notes == (), "a clean walk to the trailer"
        (packet,) = result.xmp
        assert packet.startswith(b"<x:xmpmeta")
        assert packet.endswith(b"</x:xmpmeta>"), "the magic trailer is not part of it"
        assert b"trainedAlgorithmicMedia" in packet

    def test_a_gif_without_xmp_walks_to_the_trailer_and_finds_nothing(self):
        """Reaching the end cleanly is the assertion: no note means no lost bytes."""
        result = self.scan_of(gif())

        assert result.container is Container.GIF
        assert result.segments == []
        assert result.notes == ()
        assert result.has_any_metadata is False

    def test_an_animation_is_walked_past_to_reach_the_metadata(self):
        """Four frames of LZW data plus a NETSCAPE loop block, all stepped over."""
        result = self.scan_of(gif(term="trainedAlgorithmicMedia", frames=4))

        assert result.notes == ()
        assert b"trainedAlgorithmicMedia" in result.xmp[0]


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


class TestAGifGetsARealVerdict(GifOverHttp):
    """The whole GIF story, end to end, on the engine that cannot draw.

    Three separate fixes had to land for this to say anything true. #19 stopped
    `labelled` claiming a mark the gifsicle engine cannot make; #24 computed the
    verdict at all, since Thumbor skips the phase the label filter lives in for
    every GIF; #25 read the provenance the file actually carries.
    """

    def verdict(self, image="ai.gif"):
        import json

        response = self.fetch(f"/unsafe/meta/160x120/{image}")
        assert response.code == 200, response.body[:200]
        return json.loads(response.body)["ai_label"]

    def test_the_assertion_in_the_gif_is_what_gets_reported(self):
        verdict = self.verdict()
        assert verdict["label"] == "ai_generated"
        assert verdict["reason"] == "ai_asserted"

    def test_the_disclosure_matches_the_verdict(self):
        assert self.verdict()["disclosure"] == "AI generated"

    def test_labelled_is_false_because_this_engine_cannot_draw(self):
        """The verdict is real; the pixels still carry nothing on gifsicle (#19).

        Which is the case `labelled` exists for: a CMS reading `ai_generated` beside
        `labelled: false` knows the DOM disclosure is the only one this image has.
        """
        assert self.verdict()["labelled"] is False

    def test_an_animated_gif_reports_the_same(self):
        assert self.verdict("animated.gif")["label"] == "ai_generated"
