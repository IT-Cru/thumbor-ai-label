"""IPTC DigitalSourceType detector - the primary AI provenance signal.

Named for the schema it reads, not the container that carries it: IPTC's
provenance fields live in the XMP packet, the way EXIF lives in APP1.

Deliberately does not use an XML parser. The input is attacker-controllable, and
an XML parser on untrusted input invites entity-expansion and external-entity
attacks; hardening one costs more than the targeted scan below, which is also
faster. XMP is a well-defined RDF/XML shape and the one field we need can be
located precisely.

The namespace *prefix* is discovered rather than assumed. ``Iptc4xmpExt`` is
conventional but prefixes are arbitrary in XML, so the packet is asked which
prefix it bound to the IPTC extension namespace.
"""

from __future__ import annotations

import re
from typing import List, Optional

from ..scan import ScanResult, SegmentKind
from .types import (
    IPTC_DIGITAL_SOURCE_TYPE_NS,
    Confidence,
    Detection,
    SourceType,
    resolve_iptc_term,
)

NAME = "iptc"
REQUIRES = frozenset({SegmentKind.XMP})

_CONVENTIONAL_PREFIX = "Iptc4xmpExt"

_NS_DECL = re.compile(
    r'xmlns:([A-Za-z_][\w.\-]*)\s*=\s*["\']' + re.escape(IPTC_DIGITAL_SOURCE_TYPE_NS) + r'["\']'
)

_BOMS = (
    (b"\xef\xbb\xbf", "utf-8-sig"),
    (b"\xff\xfe\x00\x00", "utf-32-le"),
    (b"\x00\x00\xfe\xff", "utf-32-be"),
    (b"\xff\xfe", "utf-16-le"),
    (b"\xfe\xff", "utf-16-be"),
)


def _decode(packet: bytes) -> str:
    """XMP may be UTF-8, UTF-16 or UTF-32; the BOM says which."""
    for bom, encoding in _BOMS:
        if packet[: len(bom)] == bom:
            return packet.decode(encoding, errors="replace")
    return packet.decode("utf-8", errors="replace")


def _prefixes(text: str) -> List[str]:
    found = [match.group(1) for match in _NS_DECL.finditer(text)]
    # A packet can bind the namespace more than once, and some writers emit the
    # field without ever declaring the namespace - fall back to the conventional
    # prefix so those are not missed.
    if _CONVENTIONAL_PREFIX not in found:
        found.append(_CONVENTIONAL_PREFIX)
    return found


def _find_value(text: str, prefix: str) -> Optional[str]:
    field = re.escape("{}:DigitalSourceType".format(prefix))

    # Attribute form: <rdf:Description Iptc4xmpExt:DigitalSourceType="..."/>
    attribute = re.search(field + r'\s*=\s*["\']([^"\']*)["\']', text)
    if attribute:
        return attribute.group(1)

    # Element form: <Iptc4xmpExt:DigitalSourceType>...</Iptc4xmpExt:DigitalSourceType>
    element = re.search(r"<" + field + r"(?:\s[^>]*)?>([^<]*)</" + field + r"\s*>", text)
    if element:
        return element.group(1)

    return None


def detect(result: ScanResult) -> Optional[Detection]:
    for packet in result.xmp:
        text = _decode(packet)
        for prefix in _prefixes(text):
            raw = _find_value(text, prefix)
            if raw is None:
                continue

            source_type, term = resolve_iptc_term(raw)
            if source_type is SourceType.UNKNOWN and term:
                # The field is present but names a term this build does not know.
                # Reporting UNKNOWN with the term as evidence is honest and lets the
                # fail-closed policy act; silently returning NOT_AI would not be.
                return Detection(
                    source_type=SourceType.UNKNOWN,
                    confidence=Confidence.HIGH,
                    detector=NAME,
                    evidence="unrecognised DigitalSourceType: {}".format(term),
                )

            return Detection(
                source_type=source_type,
                confidence=Confidence.HIGH,
                detector=NAME,
                evidence=term,
            )

    return None
