"""End-to-end through Thumbor's own machinery.

Builds a real Context, loads a real image through the wrapped engine, and runs the
real filter. This is the layer where assumptions about Thumbor's internals would
break, so it is exercised against the actual classes rather than mocks.
"""

from __future__ import annotations

import asyncio
import io

import pytest

pytest.importorskip("thumbor", reason="the Thumbor layer needs Thumbor installed")

from PIL import Image  # noqa: E402
from thumbor.config import Config  # noqa: E402
from thumbor.context import Context  # noqa: E402
from thumbor.importer import Importer  # noqa: E402

from thumbor_ai_label.label import apply, decide_for_request  # noqa: E402
from thumbor_ai_label.detect import SourceType  # noqa: E402
from thumbor_ai_label.filters.ai_label import Filter  # noqa: E402
from thumbor_ai_label.policy import Reason  # noqa: E402
from thumbor_ai_label.state import get_scan  # noqa: E402

CV = "http://cv.iptc.org/newscodes/digitalsourcetype/"
NS = 'xmlns:Iptc4xmpExt="http://iptc.org/std/Iptc4xmpExt/2008-02-29/"'


def xmp_for(term: str) -> bytes:
    return (
        '<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF><rdf:Description '
        '{ns} Iptc4xmpExt:DigitalSourceType="{cv}{term}"/></rdf:RDF></x:xmpmeta>'
    ).format(ns=NS, cv=CV, term=term).encode()


def make_jpeg(term=None, software=None, size=(600, 400), colour=(90, 120, 160)) -> bytes:
    image = Image.new("RGB", size, colour)
    kwargs = {}
    if term:
        kwargs["xmp"] = xmp_for(term)
    if software:
        tags = image.getexif()
        tags[0x0131] = software
        kwargs["exif"] = tags
    buf = io.BytesIO()
    image.save(buf, "JPEG", quality=95, **kwargs)
    return buf.getvalue()


def build_context(**overrides) -> Context:
    config = Config(
        SECURITY_KEY="test-key",
        ENGINE="thumbor_ai_label.engine",
        **overrides,
    )
    importer = Importer(config)
    importer.import_modules()
    return Context(config=config, importer=importer)


def load(context, raw: bytes):
    engine = context.modules.engine
    engine.load(raw, ".jpg")
    return engine


def corner_changed(before: Image.Image, after: Image.Image) -> bool:
    """Did anything actually get drawn in the bottom-right?"""
    w, h = before.size
    box = (w // 2, h // 2, w, h)
    return before.crop(box).tobytes() != after.crop(box).tobytes()


class TestEngineHook:
    def test_engine_is_the_wrapped_one(self):
        context = build_context()
        assert type(context.modules.engine).__name__ == "Engine"
        assert "AiLabelEngineMixin" in [c.__name__ for c in type(context.modules.engine).__mro__]

    def test_loading_stores_a_scan_result(self):
        context = build_context()
        load(context, make_jpeg(term="trainedAlgorithmicMedia"))
        scanned = get_scan(context)
        assert scanned is not None
        assert scanned.xmp

    def test_scan_is_skipped_when_disabled(self):
        context = build_context(AI_LABEL_ENABLED=False)
        load(context, make_jpeg(term="trainedAlgorithmicMedia"))
        assert get_scan(context) is None

    def test_the_image_still_loads_normally(self):
        context = build_context()
        engine = load(context, make_jpeg())
        assert engine.image is not None
        assert engine.size == (600, 400)


class TestDecisions:
    def decide(self, raw, **config):
        context = build_context(**config)
        load(context, raw)
        return asyncio.run(decide_for_request(context))

    def test_ai_image_is_labelled(self):
        decision = self.decide(make_jpeg(term="trainedAlgorithmicMedia"))
        assert decision.state is SourceType.AI_GENERATED
        assert decision.reason is Reason.AI_ASSERTED

    def test_camera_image_is_not_labelled(self):
        decision = self.decide(make_jpeg(term="digitalCapture"))
        assert decision.should_label is False
        assert decision.reason is Reason.NOT_AI_ASSERTED

    def test_plain_image_is_labelled_unknown_under_strict(self):
        decision = self.decide(make_jpeg())
        assert decision.state is SourceType.UNKNOWN

    def test_plain_image_is_left_alone_under_relaxed(self):
        decision = self.decide(make_jpeg(), AI_LABEL_POLICY="relaxed")
        assert decision.should_label is False
        assert decision.reason is Reason.NO_PROVENANCE_BLOCK

    def test_exif_vendor_hint_raises_a_label(self):
        decision = self.decide(make_jpeg(software="Midjourney v6"))
        assert decision.state is SourceType.AI_GENERATED
        assert decision.detection.confidence.value == "low"

    def test_min_confidence_can_suppress_the_heuristic(self):
        decision = self.decide(
            make_jpeg(software="Midjourney v6"),
            AI_LABEL_MIN_CONFIDENCE="high",
            AI_LABEL_POLICY="relaxed",
        )
        assert decision.state is not SourceType.AI_GENERATED

    def test_decision_is_memoised(self):
        context = build_context()
        load(context, make_jpeg(term="trainedAlgorithmicMedia"))
        first = asyncio.run(decide_for_request(context))
        second = asyncio.run(decide_for_request(context))
        assert first is second

    def test_missing_scan_is_reported_not_silently_clean(self):
        context = build_context()
        decision = asyncio.run(decide_for_request(context))
        assert decision.reason is Reason.DETECTION_DISABLED


class TestDrawing:
    def run_filter(self, raw, **config):
        context = build_context(**config)
        engine = load(context, raw)
        before = engine.image.copy()
        drawn = asyncio.run(apply(context, engine))
        return before, engine.image, drawn

    def test_label_is_drawn_for_an_ai_image(self):
        before, after, drawn = self.run_filter(make_jpeg(term="trainedAlgorithmicMedia"))
        assert drawn is True
        assert corner_changed(before, after)

    def test_nothing_is_drawn_for_a_camera_image(self):
        before, after, drawn = self.run_filter(make_jpeg(term="digitalCapture"))
        assert drawn is False
        assert not corner_changed(before, after)

    def test_small_images_are_left_alone(self):
        before, after, drawn = self.run_filter(
            make_jpeg(term="trainedAlgorithmicMedia", size=(80, 80))
        )
        assert drawn is False
        assert not corner_changed(before, after)

    def test_position_is_honoured(self):
        raw = make_jpeg(term="trainedAlgorithmicMedia")
        before, after, _ = self.run_filter(raw, AI_LABEL_POSITION="top-left")
        w, h = before.size
        top_left = (0, 0, w // 2, h // 2)
        assert before.crop(top_left).tobytes() != after.crop(top_left).tobytes()
        assert not corner_changed(before, after)

    def test_a_broken_icon_path_does_not_break_delivery(self):
        before, after, drawn = self.run_filter(
            make_jpeg(term="trainedAlgorithmicMedia"),
            AI_LABEL_ICONS={"ai_generated": "/nonexistent/icon.png"},
        )
        assert drawn is False
        assert not corner_changed(before, after)

    def test_strict_errors_turns_a_broken_icon_into_a_failure(self):
        with pytest.raises(Exception):
            self.run_filter(
                make_jpeg(term="trainedAlgorithmicMedia"),
                AI_LABEL_ICONS={"ai_generated": "/nonexistent/icon.png"},
                AI_LABEL_STRICT_ERRORS=True,
            )


class TestFilterWiring:
    def test_filter_registers_under_its_name(self):
        assert Filter.pre_compile() == "ai_label"

    def test_filter_runs_end_to_end(self):
        context = build_context()
        engine = load(context, make_jpeg(term="trainedAlgorithmicMedia"))
        before = engine.image.copy()

        instance = Filter.init_if_valid("ai_label()", context)
        assert instance is not None
        instance.engine = engine
        asyncio.run(instance.run())

        assert corner_changed(before, engine.image)


class TestFailureContainment:
    def test_a_scanner_failure_does_not_break_image_loading(self, monkeypatch):
        import thumbor_ai_label.engine as engine_module

        def explode(_buffer):
            raise RuntimeError("scanner bug")

        monkeypatch.setattr(engine_module, "scan", explode)
        context = build_context()
        engine = load(context, make_jpeg(term="trainedAlgorithmicMedia"))
        assert engine.image is not None
        assert get_scan(context) is None

    def test_no_detectors_configured_means_no_label(self):
        context = build_context(AI_LABEL_DETECTORS=[])
        load(context, make_jpeg(term="trainedAlgorithmicMedia"))
        decision = asyncio.run(decide_for_request(context))
        assert decision.reason is Reason.DETECTION_DISABLED
        assert decision.should_label is False

    def test_disabled_plugin_draws_nothing(self):
        context = build_context(AI_LABEL_ENABLED=False)
        load(context, make_jpeg(term="trainedAlgorithmicMedia"))
        decision = asyncio.run(decide_for_request(context))
        assert decision.should_label is False

    def test_an_engine_without_a_pil_image_is_skipped(self):
        from thumbor_ai_label.label import draw
        from thumbor_ai_label.policy import Decision

        context = build_context()

        class Headless:
            image = None

        decision = Decision(SourceType.AI_GENERATED, Reason.AI_ASSERTED)
        assert draw(context, Headless(), decision) is False

    def test_unreadable_config_does_not_force_strict_errors(self):
        """A context whose config cannot be read must still fail open."""
        from thumbor_ai_label.label import _strict_errors

        class Broken:
            @property
            def config(self):
                raise RuntimeError("no config here")

        assert _strict_errors(Broken()) is False


class TestPackaging:
    def test_version_is_valid_pep440(self):
        from packaging.version import Version

        import thumbor_ai_label

        Version(thumbor_ai_label.__version__)  # raises InvalidVersion if malformed

    def test_version_has_a_single_source_of_truth(self):
        """The module must report what the distribution metadata says, not a literal."""
        from importlib.metadata import version

        import thumbor_ai_label

        assert thumbor_ai_label.__version__ == version("thumbor-ai-label")

    def test_version_is_already_normalised(self):
        """A non-canonical string would be silently rewritten at build time."""
        from packaging.version import Version

        import thumbor_ai_label

        assert str(Version(thumbor_ai_label.__version__)) == thumbor_ai_label.__version__

    def test_an_uninstalled_source_tree_still_imports(self, monkeypatch):
        """Importing from a bare checkout must not raise on missing metadata."""
        import importlib
        import importlib.metadata

        from packaging.version import Version

        def missing(_name):
            raise importlib.metadata.PackageNotFoundError(_name)

        monkeypatch.setattr(importlib.metadata, "version", missing)
        module = importlib.reload(importlib.import_module("thumbor_ai_label"))
        try:
            assert Version(module.__version__)
        finally:
            monkeypatch.undo()
            importlib.reload(module)
