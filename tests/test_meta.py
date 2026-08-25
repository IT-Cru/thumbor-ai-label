"""The /meta/ endpoint, over real HTTP through Thumbor's app.

This is how a CMS obtains the verdict to write alt text or an ARIA label, which is
what Article 50(5) accessibility asks for and what a label burnt into pixels cannot
provide.
"""

from __future__ import annotations

import io
import json
import pathlib
from typing import ClassVar

import pytest

pytest.importorskip("thumbor", reason="the meta endpoint needs Thumbor installed")

from PIL import Image
from thumbor.config import Config
from thumbor.context import Context, ServerParameters
from thumbor.importer import Importer
from tornado.testing import AsyncHTTPTestCase

import thumbor_ai_label.config  # noqa: F401 - imported for the side effect of registering config keys
from thumbor_ai_label.app import AiLabelServiceApp

IMAGES = pathlib.Path(__file__).resolve().parent / "images"

AI = "01-iptc-ai-generated.jpg"
CAMERA = "04-iptc-camera.jpg"
UNKNOWN_TERM = "07-iptc-unrecognised-term.jpg"
MIDJOURNEY = "09-exif-midjourney.jpg"
PLAIN = "12-no-metadata.jpg"


class MetaCase(AsyncHTTPTestCase):
    extra_config: ClassVar[dict] = {}

    def get_app(self):
        settings = {
            "SECURITY_KEY": "test-key",
            "ALLOW_UNSAFE_URL": True,
            "ENGINE": "thumbor_ai_label.engine",
            "LOADER": "thumbor.loaders.file_loader",
            "FILE_LOADER_ROOT_PATH": str(IMAGES),
            "STORAGE": "thumbor.storages.no_storage",
            "RESULT_STORAGE": "thumbor.result_storages.no_storage",
        }
        settings.update(self.extra_config)
        config = Config(**settings)
        importer = Importer(config)
        importer.import_modules()
        server = ServerParameters(8888, "localhost", "thumbor.conf", None, "info", None)
        return AiLabelServiceApp(Context(server=server, config=config, importer=importer))

    def meta(self, image, geometry="600x400"):
        response = self.fetch(f"/unsafe/meta/{geometry}/{image}")
        assert response.code == 200, response.body[:200]
        return json.loads(response.body)

    def verdict(self, image, geometry="600x400"):
        return self.meta(image, geometry)["ai_label"]


class TestPayload(MetaCase):
    def test_thumbors_own_payload_is_untouched(self):
        """We add a sibling key; Thumbor's namespace stays Thumbor's."""
        document = self.meta(AI)
        assert "thumbor" in document
        assert {"source", "operations", "target"} <= set(document["thumbor"])

    def test_the_verdict_is_published(self):
        verdict = self.verdict(AI)
        assert verdict["label"] == "ai_generated"
        assert verdict["reason"] == "ai_asserted"
        assert verdict["policy"] == "strict"

    def test_a_disclosure_string_is_offered_for_alt_text(self):
        assert self.verdict(AI)["disclosure"] == "AI generated"

    def test_a_camera_image_reports_no_label_and_no_disclosure(self):
        verdict = self.verdict(CAMERA)
        assert verdict["label"] is None
        assert verdict["reason"] == "not_ai_asserted"
        assert "disclosure" not in verdict

    def test_unknown_provenance_is_not_phrased_as_an_ai_claim(self):
        """Someone who cannot see the image must not be told it is AI on this evidence."""
        verdict = self.verdict(UNKNOWN_TERM)
        assert verdict["label"] == "unknown"
        assert "AI generated" not in verdict["disclosure"]
        assert "could not be established" in verdict["disclosure"]

    def test_image_requests_are_unaffected(self):
        response = self.fetch(f"/unsafe/600x400/{AI}")
        assert response.code == 200
        assert Image.open(io.BytesIO(response.body)).size == (600, 400)
        assert b"ai_label" not in response.body[:2048]


class TestLabelledFlag(MetaCase):
    """`labelled` says whether the pixels carry the mark.

    When false, the DOM disclosure is the ONLY disclosure rather than a supplement,
    which is precisely what a consumer needs to know.
    """

    def test_true_when_the_image_is_large_enough(self):
        assert self.verdict(AI, "600x400")["labelled"] is True

    def test_false_below_the_minimum_size(self):
        verdict = self.verdict(AI, "100x80")
        assert verdict["label"] == "ai_generated", "still detected"
        assert verdict["labelled"] is False, "but too small to draw"

    def test_false_when_there_is_nothing_to_label(self):
        assert self.verdict(CAMERA)["labelled"] is False


class TestVerbosity(MetaCase):
    def test_evidence_is_withheld_by_default(self):
        """Evidence can hold a generation-prompt fragment; this endpoint is public."""
        verdict = self.verdict(MIDJOURNEY)
        for key in ("detector", "confidence", "evidence", "generator"):
            assert key not in verdict


class TestVerboseEnabled(MetaCase):
    extra_config: ClassVar[dict] = {"AI_LABEL_META_VERBOSE": True}

    def test_diagnostics_appear_when_asked_for(self):
        verdict = self.verdict(MIDJOURNEY)
        assert verdict["detector"] == "exif"
        assert verdict["confidence"] == "low"
        assert "Midjourney" in verdict["evidence"]
        assert verdict["generator"] == "Midjourney"


class TestDisabled(MetaCase):
    extra_config: ClassVar[dict] = {"AI_LABEL_META": False}

    def test_nothing_is_published(self):
        document = self.meta(AI)
        assert "ai_label" not in document
        assert "thumbor" in document, "the endpoint itself still works"


class TestLocalisedDisclosures(MetaCase):
    extra_config: ClassVar[dict] = {
        "AI_LABEL_META_DISCLOSURES": {
            "ai_generated": "KI-generiert",
            "unknown": "Herkunft nicht feststellbar",
        }
    }

    def test_overrides_are_used(self):
        assert self.verdict(AI)["disclosure"] == "KI-generiert"

    def test_states_left_unset_keep_their_default(self):
        assert self.verdict(UNKNOWN_TERM)["disclosure"] == "Herkunft nicht feststellbar"


class TestJsonp(MetaCase):
    extra_config: ClassVar[dict] = {"META_CALLBACK_NAME": "onMeta"}

    def test_the_verdict_survives_jsonp_wrapping(self):
        response = self.fetch(f"/unsafe/meta/600x400/{AI}")
        assert response.code == 200
        body = response.body.decode("utf-8")
        assert body.startswith("onMeta(") and body.endswith(");")
        document = json.loads(body[len("onMeta(") : -len(");")])
        assert document["ai_label"]["label"] == "ai_generated"
        assert "thumbor" in document


class TestRelaxedPolicyReported(MetaCase):
    extra_config: ClassVar[dict] = {"AI_LABEL_POLICY": "relaxed"}

    def test_the_active_policy_is_reported(self):
        assert self.verdict(AI)["policy"] == "relaxed"

    def test_a_plain_image_reports_no_label_under_relaxed(self):
        verdict = self.verdict(PLAIN)
        assert verdict["label"] is None
        assert verdict["reason"] == "no_provenance_block"


class TestRobustness(MetaCase):
    def test_an_injection_failure_leaves_the_response_valid(
        self,
    ):
        """A broken labelling feature must not break an endpoint clients rely on."""
        from thumbor_ai_label import meta as meta_module

        original = meta_module.build_payload
        meta_module.build_payload = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
        try:
            document = self.meta(AI)
        finally:
            meta_module.build_payload = original

        assert "thumbor" in document
        assert "ai_label" not in document


class TestInjectionEdges:
    """Direct tests for paths the HTTP layer cannot reach."""

    def context(self, **overrides):
        config = Config(SECURITY_KEY="k", **overrides)
        importer = Importer(config)
        importer.import_modules()
        return Context(config=config, importer=importer)

    def test_non_text_results_are_passed_through(self):
        """Belt and braces: only a meta response should ever reach this."""
        from thumbor_ai_label import meta as meta_module

        sentinel = object()
        assert meta_module.inject(self.context(), sentinel) is sentinel

    def test_json_that_is_not_an_object_is_passed_through(self):
        from thumbor_ai_label import meta as meta_module

        assert meta_module.inject(self.context(), "[1, 2, 3]") == "[1, 2, 3]"

    def test_bytes_in_bytes_out(self):
        from thumbor_ai_label import meta as meta_module

        result = meta_module.inject(self.context(), b'{"thumbor": {}}')
        assert isinstance(result, bytes)
        assert json.loads(result)["ai_label"]["label"] is None

    def test_an_unreportable_draw_check_does_not_break_the_payload(self, monkeypatch):
        from thumbor_ai_label import meta as meta_module
        from thumbor_ai_label.detect import SourceType
        from thumbor_ai_label.policy import Decision, Reason

        context = self.context()
        monkeypatch.setattr(
            meta_module, "get_settings", lambda _c: (_ for _ in ()).throw(RuntimeError("boom"))
        )
        assert (
            meta_module._would_draw(
                context, Decision(SourceType.AI_GENERATED, Reason.AI_ASSERTED), (600, 400)
            )
            is None
        )


class TestHandlerSafetyNet:
    """after_transform guarantees a verdict exists before the worker thread needs it."""

    def context(self):
        config = Config(SECURITY_KEY="k")
        importer = Importer(config)
        importer.import_modules()
        context = Context(config=config, importer=importer)
        context.request = type("Req", (), {"meta": True})()
        return context

    def handler(self, monkeypatch, context):
        import asyncio

        from thumbor.handlers import BaseHandler

        from thumbor_ai_label.handler import AiLabelImagingHandler

        async def noop(self):
            return None

        monkeypatch.setattr(BaseHandler, "after_transform", noop)
        instance = object.__new__(AiLabelImagingHandler)
        instance.context = context
        return instance, asyncio

    def test_a_missing_verdict_is_computed(self, monkeypatch):
        from thumbor_ai_label.scan import scan
        from thumbor_ai_label.state import get_decision, store_scan

        context = self.context()
        store_scan(context, scan((IMAGES / AI).read_bytes()))
        instance, asyncio = self.handler(monkeypatch, context)

        assert get_decision(context) is None
        asyncio.run(instance.after_transform())
        assert get_decision(context) is not None

    def test_a_failure_to_compute_is_logged_not_raised(self, monkeypatch):
        import thumbor_ai_label.handler as handler_module

        context = self.context()
        instance, asyncio = self.handler(monkeypatch, context)

        async def explode(_context):
            raise RuntimeError("detector meltdown")

        monkeypatch.setattr(handler_module, "decide_for_request", explode)
        asyncio.run(instance.after_transform())  # must not raise
