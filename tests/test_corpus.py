"""Run the image corpus in tests/images through the plugin.

The corpus exists to be pointed at a real Thumbor, but it is worth running here too:
these are the only fixtures produced by a real encoder rather than hand-assembled
bytes, which is exactly why they caught the EXIF UserComment field-type bug that 340
hand-built tests had missed.

The manifest asserts the *decision*. Whether a label is actually drawn also depends on
output size, so case 21 is detected as AI while drawing nothing; that half is checked
by tests in test_icons_compose.py and seen with tools/render_test_images.py.
"""

from __future__ import annotations

import asyncio
import json
import pathlib

import pytest

pytest.importorskip("thumbor", reason="the corpus runs through the Thumbor layer")

from thumbor.config import Config
from thumbor.context import Context
from thumbor.importer import Importer

import thumbor_ai_label.config  # noqa: F401 - imported for the side effect of registering config keys
from thumbor_ai_label.label import decide_for_request
from thumbor_ai_label.scan import scan
from thumbor_ai_label.state import store_scan

CORPUS = pathlib.Path(__file__).resolve().parent / "images"
MANIFEST = json.loads((CORPUS / "manifest.json").read_text())

#: Contributed output from real generators. Not generated, never rewritten, and
#: excluded from the sdist because it grows without bound as people contribute.
REAL_CORPUS = CORPUS / "real"
REAL_MANIFEST_PATH = REAL_CORPUS / "manifest.json"
REAL_MANIFEST = json.loads(REAL_MANIFEST_PATH.read_text()) if REAL_MANIFEST_PATH.is_file() else []

#: Files in a corpus directory that are not test images. Subdirectories are excluded
#: separately by an is_file() check, which is what keeps `real/` out of the synthetic
#: corpus's own integrity check.
NON_IMAGES = {"manifest.json", "README.md"}


def decide(payload: bytes, policy: str):
    config = Config(SECURITY_KEY="corpus", AI_LABEL_POLICY=policy)
    importer = Importer(config)
    importer.import_modules()
    context = Context(config=config, importer=importer)
    store_scan(context, scan(payload))
    return asyncio.run(decide_for_request(context))


def ids(entry):
    return entry["file"]


def image_names(directory):
    return {
        p.name
        for p in directory.iterdir()
        if p.is_file() and p.name not in NON_IMAGES and not p.name.startswith("contact-sheet")
    }


class TestManifestIntegrity:
    def test_manifest_is_not_empty(self):
        assert len(MANIFEST) >= 20

    def test_every_manifest_entry_exists_on_disk(self):
        missing = [e["file"] for e in MANIFEST if not (CORPUS / e["file"]).is_file()]
        assert not missing, f"manifest lists files that are not present: {missing}"

    def test_every_image_on_disk_is_in_the_manifest(self):
        """An unlisted image is an untested image."""
        listed = {e["file"] for e in MANIFEST}
        on_disk = image_names(CORPUS)
        assert on_disk == listed, (
            f"unlisted: {sorted(on_disk - listed)}, listed but absent: {sorted(listed - on_disk)}"
        )

    def test_every_entry_declares_both_policies(self):
        for entry in MANIFEST:
            assert set(entry["expected"]) == {"strict", "relaxed"}, entry["file"]


@pytest.mark.parametrize("entry", MANIFEST, ids=ids)
@pytest.mark.parametrize("policy", ["strict", "relaxed"])
def test_corpus_matches_manifest(entry, policy):
    payload = (CORPUS / entry["file"]).read_bytes()
    expected = entry["expected"][policy]

    decision = decide(payload, policy)
    actual = decision.state.value if decision.state else None

    assert actual == expected, "{} under {}: expected {!r}, got {!r} (reason: {}) - {}".format(
        entry["file"], policy, expected, actual, decision.reason.value, entry["description"]
    )


def test_the_policy_divergence_cases_actually_diverge():
    """Guards the pair that documents the whole strict/relaxed difference.

    13 carries EXIF only; 14 carries a provenance-capable XMP block. If these ever
    stop differing under relaxed, the policy has quietly collapsed into one mode.
    """
    by_name = {e["file"]: e for e in MANIFEST}
    exif_only = by_name["13-exif-only-camera.jpg"]["expected"]
    xmp_silent = by_name["14-xmp-without-sourcetype.jpg"]["expected"]

    assert exif_only["strict"] == xmp_silent["strict"] == "unknown"
    assert exif_only["relaxed"] is None
    assert xmp_silent["relaxed"] == "unknown"


# -- Contributed corpus ---------------------------------------------------
#
# Real generator output. Empty until someone contributes (see issue #2), and absent
# entirely from an sdist, so every test here has to cope with having nothing to do.

real_corpus_present = pytest.mark.skipif(
    not REAL_CORPUS.is_dir(),
    reason="contributed corpus is excluded from the sdist",
)


@real_corpus_present
class TestRealManifestIntegrity:
    def test_the_directory_has_a_manifest(self):
        """Asserted rather than implied.

        A missing manifest makes REAL_MANIFEST an empty list, which every other check
        here then satisfies vacuously so long as the directory holds no images. That is
        a narrow window, but it is one where the corpus looks healthy while its contract
        is broken.
        """
        assert REAL_MANIFEST_PATH.is_file(), (
            f"{REAL_CORPUS} exists but has no manifest.json; "
            "contributed images cannot be validated without one"
        )

    def test_every_manifest_entry_exists_on_disk(self):
        missing = [e["file"] for e in REAL_MANIFEST if not (REAL_CORPUS / e["file"]).is_file()]
        assert not missing, f"manifest lists files that are not present: {missing}"

    def test_every_image_on_disk_is_in_the_manifest(self):
        listed = {e["file"] for e in REAL_MANIFEST}
        on_disk = image_names(REAL_CORPUS)
        assert on_disk == listed, (
            f"unlisted: {sorted(on_disk - listed)}, listed but absent: {sorted(listed - on_disk)}"
        )

    def test_every_entry_names_its_source_and_both_policies(self):
        """Without a source, a failing case cannot be reproduced or reported upstream."""
        for entry in REAL_MANIFEST:
            assert entry.get("source"), f"{entry['file']} does not say what produced it"
            assert set(entry.get("expected", {})) == {"strict", "relaxed"}, entry["file"]


@pytest.mark.skipif(not REAL_MANIFEST, reason="no contributed images yet - see issue #2")
@pytest.mark.parametrize("entry", REAL_MANIFEST, ids=ids)
@pytest.mark.parametrize("policy", ["strict", "relaxed"])
def test_real_corpus_matches_manifest(entry, policy):
    """The only fixtures here not written by this project.

    A failure is more likely to be a real bug than a bad expectation: these are the
    bytes an actual generator emitted, and the synthetic corpus has already proved it
    can miss things real encoders do.
    """
    payload = (REAL_CORPUS / entry["file"]).read_bytes()
    expected = entry["expected"][policy]

    decision = decide(payload, policy)
    actual = decision.state.value if decision.state else None

    assert actual == expected, (
        f"{entry['file']} ({entry['source']}) under {policy}: "
        f"expected {expected!r}, got {actual!r} (reason: {decision.reason.value})"
    )
