"""Rebuild the bundled EU icon sets from the Commission's official archives.

The Commission published a harmonised icon set for labelling AI-generated content on
10 June 2026. The icons are free to use without attribution. This script downloads the
official PNG archive and produces the two icon sets bundled with the plugin.

    python tools/fetch_eu_icons.py

The only change made to the official artwork is a proportional downscale: the source
files are ~7500 px wide, and labels render between 20 and ~96 px. Nothing about the
design is altered. Run this rather than hand-editing the bundled files, so their
provenance stays obvious.

Source: https://digital-strategy.ec.europa.eu/en/policies/eu-icons-labelling-ai-generated-content
"""

from __future__ import annotations

import io
import pathlib
import shutil
import urllib.request
import zipfile

from PIL import Image

PNG_ARCHIVE = "https://ec.europa.eu/newsroom/dae/redirection/document/129547"

#: Height the bundled icons are stored at. Labels draw far smaller; this leaves
#: comfortable headroom without carrying multi-megabyte artwork in the wheel.
TARGET_HEIGHT = 256

ICONS = pathlib.Path(__file__).resolve().parent.parent / "ai-labels"

#: Which official file backs which label state, per bundled set.
#:
#: "black" artwork is a dark fill with light text, for light imagery; "white" is the
#: inverse, for dark imagery.
#:
#: ai_composite maps to AI MODIFIED because a composite containing AI elements is
#: exactly "pre-existing human-made content partially modified with AI".
#:
#: `unknown` is deliberately absent. The EU marks assert that content *is* AI; using
#: one on an image whose provenance merely could not be established would make a claim
#: the evidence does not support. The unknown state keeps this plugin's own neutral
#: icon, and looking visibly different from the official marks is the point.
SETS = {
    "eu": {
        "ai_generated": "LABEL_AI GENERATED_black.png",
        "ai_manipulated": "LABEL_AI MODIFIED_black.png",
        "ai_composite": "LABEL_AI MODIFIED_black.png",
    },
    "eu-white": {
        "ai_generated": "LABEL_AI GENERATED_white.png",
        "ai_manipulated": "LABEL_AI MODIFIED_white.png",
        "ai_composite": "LABEL_AI MODIFIED_white.png",
    },
}

#: Which of this plugin's own sets supplies the neutral `unknown` mark. The EU
#: artwork is picked for the imagery it sits on, so the neutral mark alongside it
#: has to be picked the same way: a dark `unknown` next to the white EU labels
#: would be the one illegible icon in the set.
UNKNOWN_SOURCE = {"eu": "default", "eu-white": "default-light"}


def main() -> None:
    print(f"downloading {PNG_ARCHIVE} ...")
    with urllib.request.urlopen(PNG_ARCHIVE) as response:
        payload = response.read()
    print(f"  {len(payload)} bytes")

    archive = zipfile.ZipFile(io.BytesIO(payload))
    available = set(archive.namelist())

    for set_name, mapping in SETS.items():
        out = ICONS / set_name
        out.mkdir(parents=True, exist_ok=True)

        for state, source in mapping.items():
            if source not in available:
                raise SystemExit(
                    f"official archive has no {source!r}; contents: {sorted(available)}"
                )
            with archive.open(source) as handle:
                icon = Image.open(io.BytesIO(handle.read())).convert("RGBA")

            width = max(1, round(icon.width * TARGET_HEIGHT / icon.height))
            icon = icon.resize((width, TARGET_HEIGHT), Image.LANCZOS)
            path = out / f"{state}.png"
            icon.save(path, "PNG", optimize=True)
            print(
                "  {}/{:<16} {:>4}x{:<4} {:>6} bytes  <- {}".format(
                    set_name,
                    state + ".png",
                    icon.width,
                    icon.height,
                    path.stat().st_size,
                    source,
                )
            )

        # The neutral unknown mark is this plugin's own, never an EU one.
        source_set = UNKNOWN_SOURCE[set_name]
        shutil.copyfile(ICONS / source_set / "unknown.png", out / "unknown.png")
        print(f"  {set_name}/unknown.png     (from {source_set}/, not an EU icon)")


if __name__ == "__main__":
    main()
