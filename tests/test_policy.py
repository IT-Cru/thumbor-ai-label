from __future__ import annotations

import pytest

from thumbor_ai_label.detect import Confidence, Detection, SourceType
from thumbor_ai_label.policy import Decision, Policy, Reason, decide
from thumbor_ai_label.scan import ScanLimits, ScanResult, SegmentKind


def scanned(*kinds) -> ScanResult:
    result = ScanResult()
    for kind in kinds:
        result.add(kind, b"payload", "test", ScanLimits())
    return result


def found(source_type, confidence=Confidence.HIGH, detector="iptc"):
    return [Detection(source_type=source_type, confidence=confidence, detector=detector)]


class TestPositiveClaims:
    @pytest.mark.parametrize("policy", list(Policy))
    @pytest.mark.parametrize(
        "state",
        [SourceType.AI_GENERATED, SourceType.AI_MANIPULATED, SourceType.AI_COMPOSITE],
    )
    def test_an_ai_claim_always_labels(self, state, policy):
        decision = decide(scanned(SegmentKind.XMP), found(state), policy)
        assert decision.state is state
        assert decision.reason is Reason.AI_ASSERTED

    @pytest.mark.parametrize("policy", list(Policy))
    def test_a_camera_claim_never_labels(self, policy):
        decision = decide(scanned(SegmentKind.XMP), found(SourceType.NOT_AI), policy)
        assert decision.should_label is False
        assert decision.reason is Reason.NOT_AI_ASSERTED


class TestStrictPolicy:
    @pytest.mark.parametrize("kinds", [(), (SegmentKind.EXIF,), (SegmentKind.XMP,)])
    def test_anything_unproven_is_labelled(self, kinds):
        decision = decide(scanned(*kinds), [], Policy.STRICT)
        assert decision.state is SourceType.UNKNOWN

    def test_an_unrecognised_term_is_labelled(self):
        decision = decide(scanned(SegmentKind.XMP), found(SourceType.UNKNOWN), Policy.STRICT)
        assert decision.state is SourceType.UNKNOWN


class TestRelaxedPolicy:
    def test_a_file_with_no_metadata_is_left_alone(self):
        decision = decide(scanned(), [], Policy.RELAXED)
        assert decision.should_label is False
        assert decision.reason is Reason.NO_PROVENANCE_BLOCK

    def test_exif_alone_does_not_count_as_provenance(self):
        """EXIF defines no provenance field, so an EXIF block asserts nothing.

        Counting it would label essentially every camera photograph ever taken.
        """
        decision = decide(scanned(SegmentKind.EXIF), [], Policy.RELAXED)
        assert decision.should_label is False

    @pytest.mark.parametrize("kind", [SegmentKind.XMP, SegmentKind.JUMBF])
    def test_a_provenance_block_that_says_nothing_is_labelled(self, kind):
        """This is where a stripped or tampered assertion shows up."""
        decision = decide(scanned(kind), [], Policy.RELAXED)
        assert decision.state is SourceType.UNKNOWN
        assert decision.reason is Reason.INCONCLUSIVE


class TestMinConfidence:
    def test_a_low_confidence_ai_claim_labels_by_default(self):
        decision = decide(
            scanned(SegmentKind.EXIF),
            found(SourceType.AI_GENERATED, Confidence.LOW, "exif"),
            Policy.RELAXED,
        )
        assert decision.state is SourceType.AI_GENERATED

    def test_raising_the_bar_suppresses_a_weak_ai_claim(self):
        decision = decide(
            scanned(SegmentKind.EXIF),
            found(SourceType.AI_GENERATED, Confidence.LOW, "exif"),
            Policy.RELAXED,
            min_confidence=Confidence.HIGH,
        )
        assert decision.state is not SourceType.AI_GENERATED
        assert decision.reason is Reason.NO_PROVENANCE_BLOCK

    def test_a_suppressed_claim_still_counts_as_unproven_under_strict(self):
        """Rejecting the evidence must not launder the image into looking clean."""
        decision = decide(
            scanned(SegmentKind.EXIF),
            found(SourceType.AI_GENERATED, Confidence.LOW, "exif"),
            Policy.STRICT,
            min_confidence=Confidence.HIGH,
        )
        assert decision.state is SourceType.UNKNOWN
        assert decision.reason is Reason.BELOW_MIN_CONFIDENCE

    def test_a_not_ai_claim_is_honoured_at_any_confidence(self):
        """Gating it would push the image into the unknown bucket and label it."""
        decision = decide(
            scanned(SegmentKind.XMP),
            found(SourceType.NOT_AI, Confidence.LOW),
            Policy.STRICT,
            min_confidence=Confidence.HIGH,
        )
        assert decision.should_label is False


class TestSerialisation:
    def test_decision_without_a_detection(self):
        data = Decision(None, Reason.NO_PROVENANCE_BLOCK).as_dict()
        assert data == {"label": None, "reason": "no_provenance_block"}

    def test_decision_with_a_detection(self):
        detection = Detection(
            SourceType.AI_GENERATED,
            Confidence.LOW,
            "exif",
            evidence="Software: Midjourney",
            generator="Midjourney",
        )
        data = Decision(SourceType.AI_GENERATED, Reason.AI_ASSERTED, detection).as_dict()
        assert data["label"] == "ai_generated"
        assert data["detector"] == "exif"
        assert data["confidence"] == "low"
        assert data["generator"] == "Midjourney"

    def test_generator_is_omitted_when_unknown(self):
        detection = Detection(SourceType.AI_GENERATED, Confidence.HIGH, "iptc")
        assert (
            "generator"
            not in Decision(SourceType.AI_GENERATED, Reason.AI_ASSERTED, detection).as_dict()
        )
