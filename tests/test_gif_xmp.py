"""How XMP sits inside a GIF, and that our fixture really does it that way.

Separate from test_gif_engine.py because none of this needs the ``gifsicle``
binary - that module skips without it, and these assertions must not.

#25 will add a GIF walker to the scanner and will read `builders.gif` as its
reference for the format, so the fixture being right to the byte is the difference
between a walker that works and one whose author debugs a parser that is fine.
"""

from __future__ import annotations

import pytest

from tests.builders import GIF_TRAILER, XMP_APP_LABEL, XMP_MAGIC_TRAILER, gif


class TestTheFixtureIsAConformantGif:
    """The XMP block built above is the real serialisation, not an approximation.

    #25 will read this file as its reference for how XMP sits in a GIF, so a fixture
    that merely happens to pass would send that walker after the wrong bytes.
    Checked against MAGIC_TRAILER_LEN in Adobe's XMP Toolkit SDK.
    """

    def test_the_magic_trailer_is_258_bytes(self):
        assert len(XMP_MAGIC_TRAILER) == 258

    def test_it_is_0x01_then_a_descending_run_then_the_block_terminator(self):
        assert XMP_MAGIC_TRAILER[0] == 0x01
        assert XMP_MAGIC_TRAILER[1:257] == bytes(range(255, -1, -1))
        assert XMP_MAGIC_TRAILER[257] == 0x00

    def test_an_xmp_aware_reader_recovers_the_packet_by_subtracting_258(self):
        """Why the byte count has to be exact, and the check that actually pins it.

        Adobe's SDK recovers the packet as `end - MAGIC_TRAILER_LEN`, and a GIF
        walker written against the spec will do the same. A trailer one byte short
        still *walks* fine - the descending run funnels either way, so the sub-block
        test below passes on both - and the error would surface only here, as a
        packet missing its last character.
        """
        raw = gif(term="trainedAlgorithmicMedia")
        start = raw.index(XMP_APP_LABEL) + len(XMP_APP_LABEL)
        end = len(raw) - len(GIF_TRAILER) - len(XMP_MAGIC_TRAILER)

        packet = raw[start:end]
        assert packet.startswith(b"<x:xmpmeta")
        assert packet.endswith(b"</x:xmpmeta>"), "a short trailer eats the closing tag"

    def test_a_reader_that_knows_nothing_of_xmp_still_walks_it_cleanly(self):
        """The property the trailer exists for, exercised rather than asserted.

        The packet is written raw rather than chunked, so a plain GIF reader walking
        length-prefixed sub-blocks runs straight through it and overshoots into the
        trailer. Each byte there is the distance left to the terminator, so wherever
        it lands it funnels to the single 0x00 - and resumes at the next GIF block
        instead of losing the stream.
        """
        raw = gif(term="trainedAlgorithmicMedia")
        start = raw.index(XMP_APP_LABEL) + len(XMP_APP_LABEL)

        position = start
        for _ in range(1000):
            size = raw[position]
            if size == 0:
                break
            position += 1 + size
        else:  # pragma: no cover - a conformant block terminates in a handful of hops
            pytest.fail("the sub-block walk never reached a terminator")

        assert raw[position + 1 :] == GIF_TRAILER, "the walk lands exactly on the GIF trailer"
