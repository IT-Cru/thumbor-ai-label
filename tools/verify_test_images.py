"""Run the test corpus through the plugin and compare against the manifest.

    python tools/verify_test_images.py

Checks every image under both policies. Exits non-zero on any mismatch, so it works
as a smoke test after a config change or a Thumbor upgrade.

This checks the *decision*, which is what the manifest can assert. Whether a label was
actually drawn also depends on output size - case 21 is detected as AI but is too small
to carry a label - so confirm the drawing by eye with tools/render_test_images.py.
"""

from __future__ import annotations

import asyncio
import json
import pathlib
import sys

from thumbor.config import Config
from thumbor.context import Context
from thumbor.importer import Importer

import thumbor_ai_label.config  # noqa: F401  (registers config keys)
from thumbor_ai_label.label import decide_for_request
from thumbor_ai_label.state import store_scan
from thumbor_ai_label.scan import scan

TESTDATA = pathlib.Path(__file__).resolve().parent.parent / "testdata"

GREEN, RED, DIM, RESET = "\033[32m", "\033[31m", "\033[2m", "\033[0m"


def decide(payload: bytes, policy: str):
    config = Config(SECURITY_KEY="verify", AI_LABEL_POLICY=policy)
    importer = Importer(config)
    importer.import_modules()
    context = Context(config=config, importer=importer)
    store_scan(context, scan(payload))
    return asyncio.run(decide_for_request(context))


def main() -> int:
    manifest = json.loads((TESTDATA / "manifest.json").read_text())
    failures = []

    header = "{:<32} {:<26} {:<26}".format("file", "strict", "relaxed")
    print(header)
    print("-" * len(header))

    for entry in manifest:
        payload = (TESTDATA / entry["file"]).read_bytes()
        cells = []
        for policy in ("strict", "relaxed"):
            expected = entry["expected"][policy]
            decision = decide(payload, policy)
            actual = decision.state.value if decision.state else None
            ok = actual == expected
            if not ok:
                failures.append((entry["file"], policy, expected, actual, decision.reason.value))
            detail = actual if actual else "no label"
            mark = GREEN + "ok " + RESET if ok else RED + "FAIL" + RESET
            cells.append("{} {:<21}".format(mark, detail))
        print("{:<32} {} {}".format(entry["file"], cells[0], cells[1]))

    print()
    if failures:
        print("{}{} mismatch(es):{}".format(RED, len(failures), RESET))
        for name, policy, expected, actual, reason in failures:
            print("  {} [{}] expected {!r}, got {!r} (reason: {})".format(
                name, policy, expected, actual, reason))
        return 1

    print("{}all {} images match the manifest under both policies{}".format(
        GREEN, len(manifest), RESET))
    return 0


if __name__ == "__main__":
    sys.exit(main())
