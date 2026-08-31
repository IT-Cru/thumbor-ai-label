"""Always-on behaviour, exercised over real HTTP through Thumbor's app.

These requests carry no filter in the URL. If a label appears, it appears because
the handler put it there - which is the whole claim being tested.
"""

from __future__ import annotations

import io
import pathlib
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

CV = "http://cv.iptc.org/newscodes/digitalsourcetype/"
NS = 'xmlns:Iptc4xmpExt="http://iptc.org/std/Iptc4xmpExt/2008-02-29/"'


def source_image(term=None) -> bytes:
    image = Image.new("RGB", (900, 600), (70, 110, 150))
    kwargs = {}
    if term:
        kwargs["xmp"] = (
            '<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF><rdf:Description '
            f'{NS} Iptc4xmpExt:DigitalSourceType="{CV}{term}"/></rdf:RDF></x:xmpmeta>'
        ).encode()
    buf = io.BytesIO()
    image.save(buf, "JPEG", quality=95, **kwargs)
    return buf.getvalue()


def bottom_right(raw: bytes, fraction: float = 0.4) -> bytes:
    image = Image.open(io.BytesIO(raw)).convert("RGB")
    w, h = image.size
    return image.crop((int(w * (1 - fraction)), int(h * (1 - fraction)), w, h)).tobytes()


class AlwaysOnCase(AsyncHTTPTestCase):
    """Base case serving three fixture images from a file loader."""

    extra_config: ClassVar[dict] = {}

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        root = pathlib.Path(cls._tmp.name)
        (root / "ai.jpg").write_bytes(source_image("trainedAlgorithmicMedia"))
        (root / "camera.jpg").write_bytes(source_image("digitalCapture"))
        (root / "plain.jpg").write_bytes(source_image())
        cls.root = root

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def get_app(self):
        settings = {
            "SECURITY_KEY": "test-key",
            "ALLOW_UNSAFE_URL": True,
            "ENGINE": "thumbor_ai_label.engine",
            "LOADER": "thumbor.loaders.file_loader",
            "FILE_LOADER_ROOT_PATH": str(self.root),
            "STORAGE": "thumbor.storages.no_storage",
            "RESULT_STORAGE": "thumbor.result_storages.no_storage",
        }
        settings.update(self.extra_config)
        config = Config(**settings)
        importer = Importer(config)
        importer.import_modules()
        server = ServerParameters(8888, "localhost", "thumbor.conf", None, "info", None)
        context = Context(server=server, config=config, importer=importer)
        return AiLabelServiceApp(context)

    def get(self, path):
        response = self.fetch(path)
        assert response.code == 200, f"{path} returned {response.code}"
        return response.body


class TestAlwaysOn(AlwaysOnCase):
    def test_an_ai_image_is_labelled_with_no_filter_in_the_url(self):
        ai = self.get("/unsafe/400x300/ai.jpg")
        camera = self.get("/unsafe/400x300/camera.jpg")
        # Same source picture and same geometry: the corner can only differ if a
        # label was drawn on one of them.
        assert bottom_right(ai) != bottom_right(camera)

    def test_a_camera_image_is_served_untouched(self):
        camera = self.get("/unsafe/400x300/camera.jpg")
        plain_render = Image.open(io.BytesIO(camera)).convert("RGB")
        assert plain_render.size == (400, 300)

    def test_an_untagged_image_is_labelled_under_the_strict_default(self):
        plain = self.get("/unsafe/400x300/plain.jpg")
        camera = self.get("/unsafe/400x300/camera.jpg")
        assert bottom_right(plain) != bottom_right(camera)

    def test_labelling_survives_a_filter_that_would_otherwise_erase_it(self):
        """The label is appended last, so a URL cannot blur or desaturate it away."""
        blurred = self.get("/unsafe/400x300/filters:blur(12)/ai.jpg")
        camera_blurred = self.get("/unsafe/400x300/filters:blur(12)/camera.jpg")
        assert bottom_right(blurred) != bottom_right(camera_blurred)

    def test_an_explicit_ai_label_filter_does_not_double_draw(self):
        implicit = self.get("/unsafe/400x300/ai.jpg")
        explicit = self.get("/unsafe/400x300/filters:ai_label()/ai.jpg")
        assert bottom_right(implicit) == bottom_right(explicit)

    def test_other_filters_still_work(self):
        raw = self.get("/unsafe/400x300/filters:grayscale()/camera.jpg")
        image = Image.open(io.BytesIO(raw)).convert("RGB")
        pixel = image.getpixel((10, 10))
        assert pixel[0] == pixel[1] == pixel[2]

    def test_small_styles_are_served_without_a_label(self):
        small_ai = self.get("/unsafe/100x80/ai.jpg")
        small_camera = self.get("/unsafe/100x80/camera.jpg")
        assert bottom_right(small_ai) == bottom_right(small_camera)

    def test_a_missing_source_still_404s(self):
        assert self.fetch("/unsafe/400x300/nope.jpg").code == 404


class TestDisabled(AlwaysOnCase):
    extra_config: ClassVar[dict] = {"AI_LABEL_ENABLED": False}

    def test_nothing_is_drawn_when_the_plugin_is_off(self):
        ai = self.get("/unsafe/400x300/ai.jpg")
        camera = self.get("/unsafe/400x300/camera.jpg")
        assert bottom_right(ai) == bottom_right(camera)


class TestRelaxedPolicy(AlwaysOnCase):
    extra_config: ClassVar[dict] = {"AI_LABEL_POLICY": "relaxed"}

    def test_an_untagged_image_is_left_alone(self):
        plain = self.get("/unsafe/400x300/plain.jpg")
        camera = self.get("/unsafe/400x300/camera.jpg")
        assert bottom_right(plain) == bottom_right(camera)

    def test_an_ai_image_is_still_labelled(self):
        ai = self.get("/unsafe/400x300/ai.jpg")
        camera = self.get("/unsafe/400x300/camera.jpg")
        assert bottom_right(ai) != bottom_right(camera)


class TestDrawStates(AlwaysOnCase):
    """Only positively detected AI gets a mark; uncertain provenance goes unmarked."""

    extra_config: ClassVar[dict] = {
        "AI_LABEL_DRAW_STATES": ["ai_generated", "ai_manipulated", "ai_composite"]
    }

    def test_an_untagged_image_is_left_alone_even_under_strict(self):
        """Strict still calls it unknown - it just no longer draws it."""
        plain = self.get("/unsafe/400x300/plain.jpg")
        camera = self.get("/unsafe/400x300/camera.jpg")
        assert bottom_right(plain) == bottom_right(camera)

    def test_an_ai_image_is_still_labelled(self):
        ai = self.get("/unsafe/400x300/ai.jpg")
        camera = self.get("/unsafe/400x300/camera.jpg")
        assert bottom_right(ai) != bottom_right(camera)


class TestPositionConfig(AlwaysOnCase):
    extra_config: ClassVar[dict] = {"AI_LABEL_POSITION": "top-left"}

    def test_the_label_moves_with_config(self):
        ai = self.get("/unsafe/400x300/ai.jpg")
        camera = self.get("/unsafe/400x300/camera.jpg")
        assert bottom_right(ai) == bottom_right(camera)

        def top_left(raw):
            image = Image.open(io.BytesIO(raw)).convert("RGB")
            return image.crop((0, 0, 160, 120)).tobytes()

        assert top_left(ai) != top_left(camera)


class TestWithSourceStorage(AlwaysOnCase):
    """Storage-hit and storage-miss load the buffer from different places.

    Production Thumbor almost always has storage enabled, and the hit path never
    calls engine.load from _fetch - it happens later in get_image. Both paths must
    produce the same labelled output.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        import tempfile

        cls._store = tempfile.TemporaryDirectory()

    @classmethod
    def tearDownClass(cls):
        cls._store.cleanup()
        super().tearDownClass()

    def get_app(self):
        type(self).extra_config = {
            "STORAGE": "thumbor.storages.file_storage",
            "FILE_STORAGE_ROOT_PATH": self._store.name,
        }
        return super().get_app()

    def test_labelling_is_identical_across_a_storage_miss_and_hit(self):
        miss_ai = self.get("/unsafe/400x300/ai.jpg")
        miss_camera = self.get("/unsafe/400x300/camera.jpg")
        assert bottom_right(miss_ai) != bottom_right(miss_camera)

        hit_ai = self.get("/unsafe/400x300/ai.jpg")
        hit_camera = self.get("/unsafe/400x300/camera.jpg")
        assert bottom_right(hit_ai) != bottom_right(hit_camera)

        assert miss_ai == hit_ai, "storage hit produced different bytes than the miss"


class TestMetaEndpoint(AlwaysOnCase):
    def test_meta_requests_still_work(self):
        """The meta path swaps in JSONEngine; the plugin must not break it."""
        import json

        body = self.get("/unsafe/meta/400x300/ai.jpg")
        payload = json.loads(body)
        assert "thumbor" in payload
        assert "target" in payload["thumbor"]


class TestWithoutTheEngineConfig(AlwaysOnCase):
    """APP_CLASS alone is enough: stock ENGINE, still labelled.

    This used to be the documented misconfiguration - APP_CLASS without ENGINE
    served every image unlabelled. The app now wraps whatever engine is configured,
    so there is nothing left to get wrong here.
    """

    def get_app(self):
        type(self).extra_config = {"ENGINE": "thumbor.engines.pil"}
        return super().get_app()

    def test_images_are_labelled_with_the_stock_engine(self):
        ai = self.get("/unsafe/400x300/ai.jpg")
        camera = self.get("/unsafe/400x300/camera.jpg")
        assert bottom_right(ai) != bottom_right(camera)

    def test_a_camera_image_is_still_left_alone(self):
        """Wrapping the engine must not turn the hook into a blanket label."""
        camera = self.get("/unsafe/400x300/camera.jpg")
        plain_camera = Image.open(io.BytesIO(camera)).convert("RGB")
        assert plain_camera.size == (400, 300)


class TestWithAForeignEngine(AlwaysOnCase):
    """The case ENGINE = "thumbor_ai_label.engine" could not express at all.

    A deployment running its own engine used to have to choose between that engine
    and being able to label; the app now composes with it.
    """

    def get_app(self):
        type(self).extra_config = {"ENGINE": "tests.foreign_engine"}
        return super().get_app()

    def test_images_are_labelled_through_the_foreign_engine(self):
        ai = self.get("/unsafe/400x300/ai.jpg")
        camera = self.get("/unsafe/400x300/camera.jpg")
        assert bottom_right(ai) != bottom_right(camera)

    def test_the_foreign_engine_still_ran(self):
        """Composed, not displaced - its load must still be the one doing the work."""
        from tests.foreign_engine import loads_seen

        loads_seen.clear()
        self.get("/unsafe/400x300/ai.jpg")
        assert loads_seen


class TestEuIconSet(AlwaysOnCase):
    """The official EU labels are wide lockups; they must render end to end."""

    def get_app(self):
        type(self).extra_config = {"AI_LABEL_ICON_SET": "eu"}
        return super().get_app()

    def test_an_ai_image_is_labelled_with_the_eu_label(self):
        ai = self.get("/unsafe/600x400/ai.jpg")
        camera = self.get("/unsafe/600x400/camera.jpg")
        assert bottom_right(ai) != bottom_right(camera)

    def test_output_geometry_is_unchanged(self):
        raw = self.get("/unsafe/600x400/ai.jpg")
        assert Image.open(io.BytesIO(raw)).size == (600, 400)

    def test_a_narrow_style_still_fits_the_wide_label(self):
        """A 3:1 lockup on a narrow crop must scale, not overflow or distort."""
        raw = self.get("/unsafe/200x400/ai.jpg")
        assert Image.open(io.BytesIO(raw)).size == (200, 400)
        camera = self.get("/unsafe/200x400/camera.jpg")
        assert bottom_right(raw) != bottom_right(camera)
