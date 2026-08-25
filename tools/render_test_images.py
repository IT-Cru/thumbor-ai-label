"""Render the test corpus through the plugin and build a contact sheet.

    python tools/render_test_images.py [--icon-set eu] [--policy strict] [--width 420]

The manifest checks the decision; this shows the drawing. Some things only a picture
tells you: whether a label is legible at your style sizes, whether it collides with
image content, and that case 21 correctly carries no label because it is under the
minimum size.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import pathlib

from PIL import Image, ImageDraw, ImageFont
from thumbor.config import Config
from thumbor.context import Context
from thumbor.importer import Importer

import thumbor_ai_label.config  # noqa: F401 - imported for the side effect of registering config keys
from thumbor_ai_label.label import apply

CORPUS = pathlib.Path(__file__).resolve().parent.parent / "tests" / "images"


def render(payload: bytes, width: int, icon_set: str, policy: str) -> Image.Image:
    config = Config(
        SECURITY_KEY="render",
        ENGINE="thumbor_ai_label.engine",
        AI_LABEL_ICON_SET=icon_set,
        AI_LABEL_POLICY=policy,
    )
    importer = Importer(config)
    importer.import_modules()
    context = Context(config=config, importer=importer)

    engine = context.modules.engine
    engine.load(payload, None)

    # Stand in for Thumbor's transform: scale to the requested style width. Never
    # upscale - otherwise the deliberately-tiny case would be blown up and would stop
    # demonstrating that images under the minimum size carry no label.
    source = engine.image
    target_w = min(width, source.width)
    height = max(1, round(source.height * target_w / source.width))
    engine.image = source.resize((target_w, height), Image.LANCZOS)

    asyncio.run(apply(context, engine))
    return engine.image.convert("RGB")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--icon-set", default="default", choices=["default", "eu", "eu-white"])
    parser.add_argument("--policy", default="strict", choices=["strict", "relaxed"])
    parser.add_argument("--width", type=int, default=420, help="style width in pixels")
    parser.add_argument("--columns", type=int, default=4)
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    manifest = json.loads((CORPUS / "manifest.json").read_text())
    rendered = []
    for entry in manifest:
        payload = (CORPUS / entry["file"]).read_bytes()
        rendered.append((entry, render(payload, args.width, args.icon_set, args.policy)))

    pad, caption_h = 12, 20
    cell_w = args.width
    columns = args.columns
    # Row heights are computed per row, not globally: one very tall image would
    # otherwise pad every other row with a screenful of blank space.
    row_groups = [rendered[i : i + columns] for i in range(0, len(rendered), columns)]
    row_heights = [max(img.height for _, img in group) + caption_h for group in row_groups]

    sheet = Image.new(
        "RGB",
        (pad + columns * (cell_w + pad), pad + sum(h + pad for h in row_heights) + 30),
        (250, 250, 250),
    )
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.load_default(size=13)
    draw.text(
        (pad, 8),
        f"icon set: {args.icon_set}    policy: {args.policy}    style width: {args.width}px",
        fill=(20, 20, 20),
        font=font,
    )

    y = 30 + pad
    for row_index, group in enumerate(row_groups):
        x = pad
        for entry, image in group:
            sheet.paste(image, (x, y))
            expected = entry["expected"][args.policy] or "no label"
            draw.text(
                (x, y + image.height + 4),
                "{}  -> {}".format(entry["file"], expected),
                fill=(60, 60, 60),
                font=font,
            )
            x += cell_w + pad
        y += row_heights[row_index] + pad

    # Default to the working directory, not the corpus: a generated sheet is an
    # artefact, and dropping it among the fixtures would make it look like one.
    out = (
        pathlib.Path(args.out)
        if args.out
        else pathlib.Path(f"contact-sheet-{args.icon_set}-{args.policy}.png")
    )
    sheet.save(out)
    print(f"wrote {out} ({sheet.width}x{sheet.height})")


if __name__ == "__main__":
    main()
