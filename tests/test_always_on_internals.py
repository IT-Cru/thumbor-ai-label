"""Failure paths of the always-on wiring, which the HTTP tests cannot reach."""

from __future__ import annotations

import pytest

pytest.importorskip("thumbor")

from thumbor.config import Config
from thumbor.filters import PHASE_POST_TRANSFORM, FiltersFactory

import thumbor_ai_label.config  # noqa: F401 - imported for the side effect of registering config keys
from thumbor_ai_label.app import AiLabelServiceApp
from thumbor_ai_label.handler import AlwaysOnFiltersFactory
from thumbor_ai_label.icons import IconError


class FakeModules:
    engine = None


class FakeContext:
    """Just enough context for BaseFilter, which reads context.modules.engine."""

    def __init__(self, **overrides):
        self.config = Config(**overrides)
        self.modules = FakeModules()


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
        assert len(factory.create_instances(self.context(), "").filter_instances[
            PHASE_POST_TRANSFORM
        ]) == 1
