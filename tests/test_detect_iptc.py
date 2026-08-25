from __future__ import annotations

import time

from thumbor_ai_label.detect import Confidence, SourceType
from thumbor_ai_label.detect import iptc as detector
from thumbor_ai_label.scan import ScanLimits, ScanResult, SegmentKind

CV = "http://cv.iptc.org/newscodes/digitalsourcetype/"
NS = "http://iptc.org/std/Iptc4xmpExt/2008-02-29/"


def scanned(*packets: bytes) -> ScanResult:
    result = ScanResult()
    for packet in packets:
        result.add(SegmentKind.XMP, packet, "test", ScanLimits())
    return result


def packet(body: str) -> bytes:
    document = '<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF>' + body + "</rdf:RDF></x:xmpmeta>"
    return document.encode()


def attribute(term: str, prefix: str = "Iptc4xmpExt") -> bytes:
    return packet(
        f'<rdf:Description xmlns:{prefix}="{NS}" {prefix}:DigitalSourceType="{CV}{term}"/>'
    )


def element(term: str, prefix: str = "Iptc4xmpExt") -> bytes:
    return packet(
        f'<rdf:Description xmlns:{prefix}="{NS}"><{prefix}:DigitalSourceType>{CV}{term}'
        f"</{prefix}:DigitalSourceType></rdf:Description>"
    )


class TestVocabulary:
    def test_generated(self):
        found = detector.detect(scanned(attribute("trainedAlgorithmicMedia")))
        assert found.source_type is SourceType.AI_GENERATED
        assert found.confidence is Confidence.HIGH
        assert found.evidence == "trainedAlgorithmicMedia"

    def test_composite(self):
        found = detector.detect(scanned(attribute("compositeWithTrainedAlgorithmicMedia")))
        assert found.source_type is SourceType.AI_COMPOSITE

    def test_camera_is_a_positive_not_ai_claim(self):
        found = detector.detect(scanned(attribute("digitalCapture")))
        assert found.source_type is SourceType.NOT_AI
        assert found.is_conclusive is True

    def test_bare_term_without_the_cv_uri(self):
        raw = packet(
            f'<rdf:Description xmlns:i="{NS}" i:DigitalSourceType="trainedAlgorithmicMedia"/>'
        )
        assert detector.detect(scanned(raw)).source_type is SourceType.AI_GENERATED

    def test_unknown_term_reports_unknown_not_clean(self):
        """An unrecognised term must never be read as a clean bill of health."""
        found = detector.detect(scanned(attribute("quantumHolographicMedia")))
        assert found.source_type is SourceType.UNKNOWN
        assert "quantumHolographicMedia" in found.evidence


class TestShapes:
    def test_element_form(self):
        assert detector.detect(scanned(element("trainedAlgorithmicMedia"))).source_type is (
            SourceType.AI_GENERATED
        )

    def test_prefix_is_discovered_not_assumed(self):
        """Prefixes are arbitrary in XML; only the namespace URI is binding."""
        found = detector.detect(scanned(attribute("trainedAlgorithmicMedia", prefix="zz")))
        assert found.source_type is SourceType.AI_GENERATED

    def test_conventional_prefix_without_a_namespace_declaration(self):
        raw = packet(
            f'<rdf:Description Iptc4xmpExt:DigitalSourceType="{CV}trainedAlgorithmicMedia"/>'
        )
        assert detector.detect(scanned(raw)).source_type is SourceType.AI_GENERATED

    def test_single_quoted_attribute(self):
        raw = packet(
            f"<rdf:Description xmlns:i=\"{NS}\" i:DigitalSourceType='{CV}trainedAlgorithmicMedia'/>"
        )
        assert detector.detect(scanned(raw)).source_type is SourceType.AI_GENERATED

    def test_element_with_attributes_on_the_tag(self):
        raw = packet(
            f'<rdf:Description xmlns:i="{NS}"><i:DigitalSourceType rdf:parseType="Literal">'
            f"{CV}trainedAlgorithmicMedia</i:DigitalSourceType></rdf:Description>"
        )
        assert detector.detect(scanned(raw)).source_type is SourceType.AI_GENERATED

    def test_utf16_packet(self):
        raw = attribute("trainedAlgorithmicMedia").decode().encode("utf-16")
        assert detector.detect(scanned(raw)).source_type is SourceType.AI_GENERATED

    def test_utf8_bom(self):
        raw = b"\xef\xbb\xbf" + attribute("trainedAlgorithmicMedia")
        assert detector.detect(scanned(raw)).source_type is SourceType.AI_GENERATED

    def test_first_packet_carrying_the_field_wins(self):
        result = scanned(
            packet('<rdf:Description dc:title="x"/>'), attribute("trainedAlgorithmicMedia")
        )
        assert detector.detect(result).source_type is SourceType.AI_GENERATED


class TestNothingToSay:
    def test_no_field_present(self):
        assert detector.detect(scanned(packet('<rdf:Description dc:title="a photo"/>'))) is None

    def test_no_xmp_at_all(self):
        assert detector.detect(ScanResult()) is None

    def test_empty_value(self):
        raw = packet(f'<rdf:Description xmlns:i="{NS}" i:DigitalSourceType=""/>')
        found = detector.detect(scanned(raw))
        assert found.source_type is SourceType.UNKNOWN

    def test_similarly_named_field_is_not_matched(self):
        raw = packet(
            f'<rdf:Description xmlns:i="{NS}" '
            f'i:DigitalSourceTypeExtra="{CV}trainedAlgorithmicMedia"/>'
        )
        assert detector.detect(scanned(raw)) is None


class TestHostileInput:
    def test_truncated_xml_does_not_raise(self):
        assert detector.detect(scanned(b'<x:xmpmeta><rdf:Desc')) is None

    def test_binary_garbage_does_not_raise(self):
        assert detector.detect(scanned(bytes(range(256)) * 4)) is None

    def test_entity_expansion_is_never_performed(self):
        """No XML parser is used, so a billion-laughs payload is inert text."""
        bomb = (
            b'<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY lol "lol">'
            + b''.join(
                b'<!ENTITY lol%d "&lol%d;&lol%d;&lol%d;&lol%d;">' % (i, i - 1, i - 1, i - 1, i - 1)
                for i in range(1, 12)
            )
            + b"]><lolz>&lol11;</lolz>"
        )
        start = time.perf_counter()
        assert detector.detect(scanned(bomb)) is None
        assert time.perf_counter() - start < 0.5

    def test_external_entity_is_not_resolved(self):
        payload = (
            b'<?xml version="1.0"?><!DOCTYPE d [<!ENTITY x SYSTEM "file:///etc/passwd">]>'
            b"<d>&x;</d>"
        )
        assert detector.detect(scanned(payload)) is None
