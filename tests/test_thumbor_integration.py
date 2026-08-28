"""End-to-end through Thumbor's own machinery.

Builds a real Context, loads a real image through the wrapped engine, and runs the
real filter. This is the layer where assumptions about Thumbor's internals would
break, so it is exercised against the actual classes rather than mocks.
"""

from __future__ import annotations

import asyncio
import io
import pathlib

import pytest

pytest.importorskip("thumbor", reason="the Thumbor layer needs Thumbor installed")

from PIL import Image
from thumbor.config import Config
from thumbor.context import Context
from thumbor.importer import Importer

from thumbor_ai_label.config import (
    get_settings,
    parse_draw_states,
    parse_icon_dir,
    parse_icon_set,
)
from thumbor_ai_label.detect import SourceType
from thumbor_ai_label.filters.ai_label import Filter
from thumbor_ai_label.icons import LABEL_STATES, IconError
from thumbor_ai_label.label import apply, decide_for_request
from thumbor_ai_label.policy import Reason
from thumbor_ai_label.state import get_scan

#: Every state except ``unknown``: the narrowing an operator is most likely to want.
AI_ONLY = ["ai_generated", "ai_manipulated", "ai_composite"]

CV = "http://cv.iptc.org/newscodes/digitalsourcetype/"
NS = 'xmlns:Iptc4xmpExt="http://iptc.org/std/Iptc4xmpExt/2008-02-29/"'


def xmp_for(term: str) -> bytes:
    return (
        '<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF><rdf:Description '
        f'{NS} Iptc4xmpExt:DigitalSourceType="{CV}{term}"/></rdf:RDF></x:xmpmeta>'
    ).encode()


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
        from thumbor_ai_label.icons import IconError

        with pytest.raises(IconError):
            self.run_filter(
                make_jpeg(term="trainedAlgorithmicMedia"),
                AI_LABEL_ICONS={"ai_generated": "/nonexistent/icon.png"},
                AI_LABEL_STRICT_ERRORS=True,
            )


class TestDrawStates:
    """`AI_LABEL_DRAW_STATES` decides which verdicts reach the pixels.

    Suppressing a state is not the same as not detecting it: the verdict is still
    computed and still published on /meta/. See test_meta.py for that half.
    """

    def run_filter(self, raw, **config):
        context = build_context(**config)
        engine = load(context, raw)
        before = engine.image.copy()
        drawn = asyncio.run(apply(context, engine))
        return before, engine.image, drawn

    def test_unknown_can_be_left_unmarked(self):
        """The case the key exists for: fail-closed detection, no mark on a maybe."""
        before, after, drawn = self.run_filter(make_jpeg(), AI_LABEL_DRAW_STATES=AI_ONLY)
        assert drawn is False
        assert not corner_changed(before, after)

    def test_a_state_left_in_is_still_drawn(self):
        before, after, drawn = self.run_filter(
            make_jpeg(term="trainedAlgorithmicMedia"),
            AI_LABEL_DRAW_STATES=AI_ONLY,
        )
        assert drawn is True
        assert corner_changed(before, after)

    def test_the_verdict_survives_suppression(self):
        """Suppression is about pixels only; the decision is untouched."""
        context = build_context(AI_LABEL_DRAW_STATES=AI_ONLY)
        load(context, make_jpeg())
        decision = asyncio.run(decide_for_request(context))
        assert decision.state is SourceType.UNKNOWN
        assert decision.reason is Reason.INCONCLUSIVE

    def test_an_empty_list_draws_nothing_at_all(self):
        """Meta-only mode: verdicts published, no pixels touched."""
        before, after, drawn = self.run_filter(
            make_jpeg(term="trainedAlgorithmicMedia"),
            AI_LABEL_DRAW_STATES=[],
        )
        assert drawn is False
        assert not corner_changed(before, after)

    def test_the_default_draws_every_state(self):
        assert parse_draw_states(None) == frozenset(LABEL_STATES)

    def test_a_comma_separated_string_is_accepted(self):
        """A value passed through the environment arrives as a string, not a list."""
        assert parse_draw_states("ai_generated, unknown") == {
            SourceType.AI_GENERATED,
            SourceType.UNKNOWN,
        }

    def test_an_empty_string_reads_as_unset(self):
        """An unrendered template variable must not silently disable labelling."""
        assert parse_draw_states("") == frozenset(LABEL_STATES)
        assert parse_draw_states("  ") == frozenset(LABEL_STATES)

    def test_case_is_not_significant(self):
        assert parse_draw_states(["AI_Generated"]) == {SourceType.AI_GENERATED}

    def test_an_unknown_state_name_is_rejected(self):
        with pytest.raises(ValueError, match="unknown label state"):
            parse_draw_states(["ai_hallucinated"])

    def test_not_ai_is_rejected_because_it_never_draws(self):
        """A positively identified photograph has no mark to suppress."""
        with pytest.raises(ValueError, match="unknown label state"):
            parse_draw_states(["not_ai"])

    def test_a_bad_state_name_does_not_break_delivery(self):
        before, after, drawn = self.run_filter(
            make_jpeg(term="trainedAlgorithmicMedia"),
            AI_LABEL_DRAW_STATES=["nope"],
        )
        assert drawn is False
        assert not corner_changed(before, after)

    def test_a_bad_state_name_is_fatal_under_strict_errors(self):
        with pytest.raises(ValueError, match="unknown label state"):
            self.run_filter(
                make_jpeg(term="trainedAlgorithmicMedia"),
                AI_LABEL_DRAW_STATES=["nope"],
                AI_LABEL_STRICT_ERRORS=True,
            )


class TestIconDir:
    """`AI_LABEL_ICON_DIR` is how a house set ships: a mounted volume, not a rebuild.

    Both this and `AI_LABEL_ICON_SET` are strings, so unlike the dict-valued
    `AI_LABEL_ICONS` the pair survives a config rendered from the environment.
    """

    def house_set(self, tmp_path, name="house-style", colour=(255, 0, 0, 255)):
        directory = tmp_path / name
        directory.mkdir()
        for state in LABEL_STATES:
            Image.new("RGBA", (64, 64), colour).save(directory / f"{state.value}.png")
        return directory

    def test_the_configured_directory_reaches_the_icon_set(self, tmp_path):
        """The gap this closes: IconSet took the parameter, config never passed it."""
        self.house_set(tmp_path)
        settings = get_settings(
            build_context(
                AI_LABEL_ICON_DIR=str(tmp_path),
                AI_LABEL_ICON_SET="house-style",
            ).config
        )

        assert settings.icons.name == "house-style"
        for state in LABEL_STATES:
            assert settings.icons.get(state, 64).getpixel((32, 32)) == (255, 0, 0, 255)

    def test_the_house_mark_is_what_lands_on_the_image(self, tmp_path):
        self.house_set(tmp_path)
        context = build_context(
            AI_LABEL_ICON_DIR=str(tmp_path),
            AI_LABEL_ICON_SET="house-style",
        )
        engine = load(context, make_jpeg(term="trainedAlgorithmicMedia"))
        assert asyncio.run(apply(context, engine)) is True

        width, height = engine.image.size
        corner = engine.image.crop((width // 2, height // 2, width, height)).convert("RGB")
        assert any(colour == (255, 0, 0) for _, colour in corner.getcolors(maxcolors=1 << 20))

    def test_leaving_it_unset_keeps_the_bundled_artwork(self):
        settings = get_settings(build_context().config)
        assert settings.icons.name == "default"
        assert settings.icons.get(SourceType.AI_GENERATED, 32).height == 32

    def test_a_missing_house_set_does_not_take_down_delivery(self, tmp_path):
        """Same shape as every other icon failure: loud in the log, image still served."""
        context = build_context(
            AI_LABEL_ICON_DIR=str(tmp_path),
            AI_LABEL_ICON_SET="typo-style",
        )
        engine = load(context, make_jpeg(term="trainedAlgorithmicMedia"))
        before = engine.image.copy()
        assert asyncio.run(apply(context, engine)) is False
        assert not corner_changed(before, engine.image)

    def test_a_missing_house_set_is_fatal_under_strict_errors(self, tmp_path):
        context = build_context(
            AI_LABEL_ICON_DIR=str(tmp_path),
            AI_LABEL_ICON_SET="typo-style",
            AI_LABEL_STRICT_ERRORS=True,
        )
        engine = load(context, make_jpeg(term="trainedAlgorithmicMedia"))
        with pytest.raises(IconError, match="AI_LABEL_ICON_DIR"):
            asyncio.run(apply(context, engine))

    def test_a_bundled_name_is_not_a_silent_fallback(self, tmp_path):
        """A typo in a house name must fail, not ship this plugin's default marks."""
        self.house_set(tmp_path)
        with pytest.raises(IconError, match="do not resolve"):
            get_settings(
                build_context(
                    AI_LABEL_ICON_DIR=str(tmp_path),
                    AI_LABEL_ICON_SET="default",
                    AI_LABEL_STRICT_ERRORS=True,
                ).config
            )

    def test_the_default_is_the_bundled_directory(self):
        assert parse_icon_dir(None) is None

    def test_an_empty_string_reads_as_unset(self):
        """An unrendered template variable must not become a relative directory."""
        assert parse_icon_dir("") is None
        assert parse_icon_dir("   ") is None

    def test_a_padded_path_is_used_rather_than_reported_missing(self):
        """Whitespace is invisible in a config file and in the error it would cause."""
        assert parse_icon_dir("  /etc/thumbor/icon-sets  ") == pathlib.Path(
            "/etc/thumbor/icon-sets"
        )

    def test_the_set_name_reads_an_empty_value_the_same_way(self):
        """Both keys render from the same template; both must survive it unrendered."""
        assert parse_icon_set(None) == "default"
        assert parse_icon_set("") == "default"
        assert parse_icon_set("   ") == "default"

    def test_a_padded_set_name_is_stripped(self):
        assert parse_icon_set("  eu-white  ") == "eu-white"

    def test_an_empty_set_name_beside_a_house_directory_still_fails(self, tmp_path):
        """The case that must not fall back: house dir configured, name unrendered."""
        self.house_set(tmp_path)
        with pytest.raises(IconError, match="do not resolve"):
            get_settings(
                build_context(
                    AI_LABEL_ICON_DIR=str(tmp_path),
                    AI_LABEL_ICON_SET="",
                    AI_LABEL_STRICT_ERRORS=True,
                ).config
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
