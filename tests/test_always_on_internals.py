"""Failure paths of the always-on wiring, which the HTTP tests cannot reach."""

from __future__ import annotations

import pytest

pytest.importorskip("thumbor")

from thumbor.config import Config
from thumbor.context import Context
from thumbor.engines.pil import Engine as PilEngine
from thumbor.filters import PHASE_POST_TRANSFORM, FiltersFactory
from thumbor.importer import Importer

import thumbor_ai_label.config  # noqa: F401 - imported for the side effect of registering config keys
from thumbor_ai_label.app import AiLabelServiceApp
from thumbor_ai_label.engine import AiLabelEngineMixin
from thumbor_ai_label.handler import AlwaysOnFiltersFactory
from thumbor_ai_label.icons import IconError


class FakeModules:
    engine = None


class FakeContext:
    """Just enough context for BaseFilter, which reads context.modules.engine."""

    def __init__(self, **overrides):
        self.config = Config(**overrides)
        self.modules = FakeModules()


class BadImporterContext:
    """A context whose importer cannot be inspected, to exercise the failure path."""

    class Modules:
        # Not a class, so issubclass() raises rather than answering.
        importer = type("BrokenImporter", (), {"engine": 42, "gif_engine": None})()

    def __init__(self, **overrides):
        self.config = Config(**overrides)
        self.modules = self.Modules()


def real_context(**overrides) -> Context:
    config = Config(**overrides)
    importer = Importer(config)
    importer.import_modules()
    return Context(config=config, importer=importer)


class TestEngineHookInstall:
    """The app wraps whatever engines are configured, rather than being one.

    `ENGINE` is a single slot, so owning it made this plugin mutually exclusive
    with every other custom engine.
    """

    def test_the_configured_engine_is_wrapped(self):
        context = real_context()
        assert not issubclass(context.modules.importer.engine, AiLabelEngineMixin)

        AiLabelServiceApp._install_engine_hook(context)

        wrapped = context.modules.importer.engine
        assert issubclass(wrapped, AiLabelEngineMixin)
        assert issubclass(wrapped, PilEngine)

    def test_a_foreign_engine_is_composed_not_replaced(self):
        """The case ENGINE = "thumbor_ai_label.engine" could not express."""
        from tests.foreign_engine import Engine as Foreign

        context = real_context(ENGINE="tests.foreign_engine")
        AiLabelServiceApp._install_engine_hook(context)

        wrapped = context.modules.importer.engine
        assert issubclass(wrapped, AiLabelEngineMixin)
        assert issubclass(wrapped, Foreign)
        # Ours first, so our load wraps theirs rather than the other way round.
        assert wrapped.__mro__.index(AiLabelEngineMixin) < wrapped.__mro__.index(Foreign)

    def test_the_gif_engine_is_wrapped_too(self):
        """With USE_GIFSICLE_ENGINE, GIFs load through a separate slot entirely.

        Hooking only ENGINE left those images unscanned - a gap in every release up
        to v0.2.0. Wrapping the slot is the fix and is what this asserts; loading a
        GIF through it needs the gifsicle binary, which CI does not install, so the
        round trip is not exercised anywhere.
        """
        context = real_context()
        AiLabelServiceApp._install_engine_hook(context)
        assert issubclass(context.modules.importer.gif_engine, AiLabelEngineMixin)

    def test_a_fresh_per_request_context_gets_the_wrapped_engine(self):
        """Patching the shared importer is what makes this reach real requests."""
        context = real_context()
        AiLabelServiceApp._install_engine_hook(context)

        # Exactly how ContextHandler.initialize builds a request's context.
        request_context = Context(config=context.config, importer=context.modules.importer)
        assert isinstance(request_context.modules.engine, AiLabelEngineMixin)

    def test_installing_twice_does_not_double_wrap(self):
        """A second wrap would run the scan twice on every image."""
        context = real_context()
        AiLabelServiceApp._install_engine_hook(context)
        once = context.modules.importer.engine

        AiLabelServiceApp._install_engine_hook(context)

        assert context.modules.importer.engine is once

    def test_our_own_engine_is_left_alone(self):
        """ENGINE = "thumbor_ai_label.engine" stays supported and must not be rewrapped."""
        context = real_context(ENGINE="thumbor_ai_label.engine")
        before = context.modules.importer.engine

        AiLabelServiceApp._install_engine_hook(context)

        assert context.modules.importer.engine is before

    def test_what_was_wrapped_is_logged(self, caplog):
        """A wrapped third-party engine looks identical to an unwrapped one."""
        caplog.set_level("INFO")
        AiLabelServiceApp._install_engine_hook(real_context())
        assert any(
            "engine hook installed on" in r.getMessage() and "thumbor.engines.pil" in r.getMessage()
            for r in caplog.records
        )

    def test_having_nothing_to_wrap_is_logged(self, caplog):
        caplog.set_level("INFO")
        context = real_context(
            ENGINE="thumbor_ai_label.engine",
            GIF_ENGINE="thumbor_ai_label.engine",
        )
        AiLabelServiceApp._install_engine_hook(context)
        assert any("already present" in r.getMessage() for r in caplog.records)

    def test_a_context_without_an_importer_is_ignored(self):
        """Nothing to patch is not an error; it just means no hook."""
        AiLabelServiceApp._install_engine_hook(FakeContext())

    def test_a_broken_importer_is_reported_but_does_not_stop_boot(self, caplog):
        AiLabelServiceApp._install_engine_hook(BadImporterContext())
        assert any(
            "could not install the engine hook" in r.getMessage() and r.levelname == "ERROR"
            for r in caplog.records
        )

    def test_a_broken_importer_is_fatal_under_strict_errors(self):
        with pytest.raises(TypeError):
            AiLabelServiceApp._install_engine_hook(BadImporterContext(AI_LABEL_STRICT_ERRORS=True))


class TestBootValidation:
    def test_valid_config_passes(self, caplog):
        AiLabelServiceApp._validate(FakeContext())
        assert not [r for r in caplog.records if r.levelname == "ERROR"]

    def test_invalid_config_is_reported_but_does_not_stop_boot(self, caplog):
        """A typo'd icon path should be loud, not fatal, by default."""
        context = FakeContext(AI_LABEL_ICONS={"ai_generated": "/nowhere/x.png"})
        AiLabelServiceApp._validate(context)
        assert any(r.levelname == "ERROR" for r in caplog.records)

    def test_strict_errors_makes_invalid_config_fatal(self):
        context = FakeContext(
            AI_LABEL_ICONS={"ai_generated": "/nowhere/x.png"},
            AI_LABEL_STRICT_ERRORS=True,
        )
        with pytest.raises(IconError):
            AiLabelServiceApp._validate(context)

    def test_unknown_detector_name_is_caught_at_boot(self, caplog):
        AiLabelServiceApp._validate(FakeContext(AI_LABEL_DETECTORS=["not-a-detector"]))
        assert any(r.levelname == "ERROR" for r in caplog.records)

    def test_being_disabled_is_announced(self, caplog):
        AiLabelServiceApp._validate(FakeContext(AI_LABEL_ENABLED=False))
        assert any("AI_LABEL_ENABLED is False" in r.getMessage() for r in caplog.records)

    def test_having_no_detectors_is_announced(self, caplog):
        AiLabelServiceApp._validate(FakeContext(AI_LABEL_DETECTORS=[]))
        assert any("no detectors configured" in r.getMessage() for r in caplog.records)

    def test_the_icon_set_in_use_is_named(self, caplog):
        """With AI_LABEL_ICON_DIR set, 'default' is not one fixed set of artwork."""
        caplog.set_level("INFO")
        AiLabelServiceApp._validate(FakeContext(AI_LABEL_ICON_SET="eu"))
        assert any("icon_set=eu" in r.getMessage() for r in caplog.records)

    def test_a_narrowed_draw_state_list_is_announced(self, caplog):
        """Dropping a state weakens the disclosure, so the operator gets told."""
        AiLabelServiceApp._validate(
            FakeContext(AI_LABEL_DRAW_STATES=["ai_generated", "ai_manipulated", "ai_composite"])
        )
        message = next(
            r.getMessage() for r in caplog.records if "AI_LABEL_DRAW_STATES" in r.getMessage()
        )
        assert "unknown" in message

    def test_an_empty_draw_state_list_is_announced(self, caplog):
        AiLabelServiceApp._validate(FakeContext(AI_LABEL_DRAW_STATES=[]))
        assert any("AI_LABEL_DRAW_STATES is empty" in r.getMessage() for r in caplog.records)

    def test_the_full_default_says_nothing(self, caplog):
        AiLabelServiceApp._validate(FakeContext())
        assert not [
            r
            for r in caplog.records
            if "AI_LABEL_DRAW_STATES" in r.getMessage() and r.levelname == "WARNING"
        ]

    def test_a_bad_draw_state_name_is_caught_at_boot(self, caplog):
        AiLabelServiceApp._validate(FakeContext(AI_LABEL_DRAW_STATES=["nope"]))
        assert any(r.levelname == "ERROR" for r in caplog.records)


class TestFactoryWrapper:
    def context(self):
        return FakeContext()

    def test_the_label_filter_is_appended_to_every_request(self):
        factory = AlwaysOnFiltersFactory(FiltersFactory([]))
        runner = factory.create_instances(self.context(), "")
        assert len(runner.filter_instances[PHASE_POST_TRANSFORM]) == 1

    def test_it_appends_rather_than_replaces(self):
        """Existing filters must survive, and the label must run after them."""
        from thumbor.filters.grayscale import Filter as Grayscale

        factory = AlwaysOnFiltersFactory(FiltersFactory([Grayscale]))
        runner = factory.create_instances(self.context(), "grayscale()")
        instances = runner.filter_instances[PHASE_POST_TRANSFORM]
        assert len(instances) == 2
        assert type(instances[-1]).__module__.startswith("thumbor_ai_label")

    def test_the_filter_is_registered_by_name_for_explicit_urls(self):
        inner = FiltersFactory([])
        AlwaysOnFiltersFactory(inner)
        assert "ai_label" in inner.filter_classes_map

    def test_an_existing_registration_is_not_clobbered(self):
        from thumbor_ai_label.filters.ai_label import Filter as Real

        class Other(Real):
            pass

        inner = FiltersFactory([])
        inner.filter_classes_map["ai_label"] = Other
        AlwaysOnFiltersFactory(inner)
        assert inner.filter_classes_map["ai_label"] is Other

    def test_an_uninstantiable_filter_is_logged_not_raised(self, caplog):
        class Unbuildable:
            phase = PHASE_POST_TRANSFORM

            @staticmethod
            def pre_compile():
                return "ai_label"

            @staticmethod
            def init_if_valid(param, context):
                return None

        factory = AlwaysOnFiltersFactory(FiltersFactory([]), filter_cls=Unbuildable)
        runner = factory.create_instances(self.context(), "")
        assert runner.filter_instances[PHASE_POST_TRANSFORM] == []
        assert any("could not instantiate" in r.getMessage() for r in caplog.records)

    def test_an_exploding_filter_does_not_cost_the_user_their_image(self, caplog):
        class Exploding:
            phase = PHASE_POST_TRANSFORM

            @staticmethod
            def pre_compile():
                return "ai_label"

            @staticmethod
            def init_if_valid(param, context):
                raise RuntimeError("boom")

        factory = AlwaysOnFiltersFactory(FiltersFactory([]), filter_cls=Exploding)
        runner = factory.create_instances(self.context(), "")
        assert runner is not None
        assert any(r.levelname == "ERROR" for r in caplog.records)

    def test_unrelated_factory_attributes_still_work(self):
        inner = FiltersFactory([])
        wrapper = AlwaysOnFiltersFactory(inner)
        assert wrapper.filter_classes_map is inner.filter_classes_map

    def test_a_factory_without_a_class_map_is_tolerated(self):
        class Bare:
            @staticmethod
            def create_instances(context, params):
                import collections

                from thumbor.filters import FiltersRunner

                return FiltersRunner(collections.defaultdict(list))

        factory = AlwaysOnFiltersFactory(Bare())
        assert (
            len(factory.create_instances(self.context(), "").filter_instances[PHASE_POST_TRANSFORM])
            == 1
        )
