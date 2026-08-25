from __future__ import annotations

import asyncio
from typing import ClassVar

import pytest

from thumbor_ai_label.detect import (
    Confidence,
    Detection,
    DetectorConfigurationError,
    SourceType,
    best_detection,
    load_detectors,
    registry,
    run_detectors,
)
from thumbor_ai_label.scan import ScanLimits, ScanResult, SegmentKind


def scanned(*kinds) -> ScanResult:
    result = ScanResult()
    for kind in kinds:
        result.add(kind, b"payload", "test", ScanLimits())
    return result


def run(coro):
    return asyncio.run(coro)


def stub(name, verdict=None, requires=frozenset(), boom=False, async_=False, calls=None):
    class Stub:
        NAME = name
        REQUIRES = requires

        @staticmethod
        def detect(result):
            if calls is not None:
                calls.append(name)
            if boom:
                raise RuntimeError("detector exploded")
            return verdict

        @staticmethod
        async def adetect(result):
            if calls is not None:
                calls.append(name)
            return verdict

    if async_:
        Stub.detect = Stub.adetect
    return Stub


def verdict(source_type, confidence=Confidence.HIGH, name="stub"):
    return Detection(source_type=source_type, confidence=confidence, detector=name)


class TestLoading:
    def test_defaults_put_the_standard_signal_first(self):
        names = [d.name for d in load_detectors()]
        assert names[0] == "iptc"
        assert "exif" in names

    def test_config_order_is_respected(self):
        names = [d.name for d in load_detectors(["exif", "iptc"])]
        assert names == ["exif", "iptc"]

    def test_a_subset_can_be_selected(self):
        assert [d.name for d in load_detectors(["iptc"])] == ["iptc"]

    def test_empty_selection_disables_detection(self):
        assert load_detectors([]) == []

    def test_unknown_name_fails_at_load_not_per_request(self):
        """Silently skipping a misconfigured detector would fail open."""
        with pytest.raises(DetectorConfigurationError) as excinfo:
            load_detectors(["iptc", "nope"])
        assert "nope" in str(excinfo.value)
        assert "iptc" in str(excinfo.value)

    def test_requires_is_read_from_the_detector(self):
        loaded = load_detectors(["iptc"])[0]
        assert loaded.requires == frozenset({SegmentKind.XMP})


class TestEntryPoints:
    def test_third_party_detector_is_discovered(self, monkeypatch):
        class Point:
            name = "house_dam"

            @staticmethod
            def load():
                return stub("house_dam", verdict(SourceType.AI_GENERATED))

        monkeypatch.setattr(registry, "entry_points", lambda group: [Point()])
        assert [d.name for d in load_detectors(["house_dam"])] == ["house_dam"]

    def test_builtins_alone_do_not_trigger_discovery(self, monkeypatch):
        def explode(group):
            raise AssertionError("discovery should not have run")

        monkeypatch.setattr(registry, "entry_points", explode)
        load_detectors(["iptc", "exif"])

    def test_a_broken_entry_point_does_not_stop_the_others(self, monkeypatch):
        class Broken:
            name = "broken"

            @staticmethod
            def load():
                raise ImportError("missing dependency")

        class Good:
            name = "good"

            @staticmethod
            def load():
                return stub("good")

        monkeypatch.setattr(registry, "entry_points", lambda group: [Broken(), Good()])
        assert [d.name for d in load_detectors(["good"])] == ["good"]

    def test_unreadable_entry_point_group_does_not_stop_boot(self, monkeypatch):
        monkeypatch.setattr(
            registry, "entry_points", lambda group: (_ for _ in ()).throw(OSError("broken dist"))
        )
        with pytest.raises(DetectorConfigurationError):
            load_detectors(["whatever"])

    def test_object_without_detect_is_rejected(self, monkeypatch):
        class Point:
            name = "bad"

            @staticmethod
            def load():
                return object()

        monkeypatch.setattr(registry, "entry_points", lambda group: [Point()])
        with pytest.raises(DetectorConfigurationError):
            load_detectors(["bad"])


class TestRunning:
    def test_detector_is_skipped_when_its_segment_kind_is_absent(self):
        calls = []
        detectors = [
            registry.Detector.adapt(
                "x", stub("x", requires=frozenset({SegmentKind.XMP}), calls=calls)
            )
        ]
        run(run_detectors(scanned(SegmentKind.EXIF), detectors))
        assert calls == []

    def test_detector_runs_when_its_kind_is_present(self):
        calls = []
        detectors = [
            registry.Detector.adapt(
                "x", stub("x", requires=frozenset({SegmentKind.XMP}), calls=calls)
            )
        ]
        run(run_detectors(scanned(SegmentKind.XMP), detectors))
        assert calls == ["x"]

    def test_async_detector_is_awaited(self):
        detectors = [
            registry.Detector.adapt(
                "remote", stub("remote", verdict(SourceType.AI_GENERATED), async_=True)
            )
        ]
        found = run(run_detectors(scanned(SegmentKind.XMP), detectors))
        assert found[0].source_type is SourceType.AI_GENERATED

    def test_a_conclusive_verdict_short_circuits(self):
        calls = []
        detectors = [
            registry.Detector.adapt(
                "first", stub("first", verdict(SourceType.AI_GENERATED), calls=calls)
            ),
            registry.Detector.adapt(
                "second", stub("second", verdict(SourceType.NOT_AI), calls=calls)
            ),
        ]
        found = run(run_detectors(scanned(SegmentKind.XMP), detectors))
        assert calls == ["first"]
        assert len(found) == 1

    def test_a_low_confidence_verdict_does_not_short_circuit(self):
        calls = []
        detectors = [
            registry.Detector.adapt(
                "weak", stub("weak", verdict(SourceType.AI_GENERATED, Confidence.LOW), calls=calls)
            ),
            registry.Detector.adapt(
                "strong", stub("strong", verdict(SourceType.NOT_AI), calls=calls)
            ),
        ]
        found = run(run_detectors(scanned(SegmentKind.XMP), detectors))
        assert calls == ["weak", "strong"]
        assert len(found) == 2

    def test_an_unknown_verdict_does_not_short_circuit(self):
        calls = []
        detectors = [
            registry.Detector.adapt("a", stub("a", verdict(SourceType.UNKNOWN), calls=calls)),
            registry.Detector.adapt("b", stub("b", verdict(SourceType.AI_GENERATED), calls=calls)),
        ]
        run(run_detectors(scanned(SegmentKind.XMP), detectors))
        assert calls == ["a", "b"]

    def test_a_raising_detector_is_contained(self):
        calls = []
        detectors = [
            registry.Detector.adapt("bad", stub("bad", boom=True, calls=calls)),
            registry.Detector.adapt(
                "good", stub("good", verdict(SourceType.AI_GENERATED), calls=calls)
            ),
        ]
        found = run(run_detectors(scanned(SegmentKind.XMP), detectors))
        assert calls == ["bad", "good"]
        assert len(found) == 1
        assert found[0].source_type is SourceType.AI_GENERATED

    def test_detectors_returning_nothing_yield_no_detections(self):
        detectors = [registry.Detector.adapt("quiet", stub("quiet"))]
        assert run(run_detectors(scanned(SegmentKind.XMP), detectors)) == []


class TestBestDetection:
    def test_nothing_found(self):
        assert best_detection([]) is None

    def test_high_confidence_beats_low(self):
        found = best_detection(
            [
                verdict(SourceType.AI_GENERATED, Confidence.LOW, "weak"),
                verdict(SourceType.NOT_AI, Confidence.HIGH, "strong"),
            ]
        )
        assert found.detector == "strong"

    def test_an_ai_claim_wins_a_tie(self):
        """A file asserting both is self-contradictory; the cautious reading wins."""
        found = best_detection(
            [
                verdict(SourceType.NOT_AI, Confidence.HIGH, "clean"),
                verdict(SourceType.AI_GENERATED, Confidence.HIGH, "ai"),
            ]
        )
        assert found.detector == "ai"

    def test_a_real_claim_beats_unknown_at_equal_confidence(self):
        found = best_detection(
            [
                verdict(SourceType.UNKNOWN, Confidence.HIGH, "puzzled"),
                verdict(SourceType.NOT_AI, Confidence.HIGH, "clean"),
            ]
        )
        assert found.detector == "clean"


class TestAdaptation:
    def test_lowercase_attributes_are_accepted(self):
        """A detector may be a plain object rather than a module."""

        class Instance:
            name = "instance"
            requires: ClassVar[set] = {SegmentKind.EXIF}

            def detect(self, result):
                return verdict(SourceType.AI_GENERATED, name="instance")

        adapted = registry.Detector.adapt("instance", Instance())
        assert adapted.name == "instance"
        assert adapted.requires == frozenset({SegmentKind.EXIF})
        found = run(run_detectors(scanned(SegmentKind.EXIF), [adapted]))
        assert found[0].source_type is SourceType.AI_GENERATED

    def test_a_detector_without_requires_runs_on_anything(self):
        class Anything:
            def detect(self, result):
                return verdict(SourceType.UNKNOWN)

        adapted = registry.Detector.adapt("anything", Anything())
        assert adapted.requires == frozenset()
        assert len(run(run_detectors(scanned(SegmentKind.XMP), [adapted]))) == 1
