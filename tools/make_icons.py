"""Generate the default label icons.

The icons are drawn from code rather than committed as opaque binaries so the
design is reviewable and reproducible. Run after changing anything here:

    python tools/make_icons.py

Design constraints, in priority order:

1. Legible at ~32 px, which is where most of these will actually be seen.
2. Readable over any underlying image - hence a dark translucent disc behind a
   light glyph, rather than a glyph laid directly on unknown pixels.
3. No font dependency. Glyphs are drawn as strokes, so output is identical on
   every machine and no font file has to be shipped or licensed.
4. Differentiated by more than colour, so the set survives greyscale printing and
   does not rely on colour vision.
"""

from __future__ import annotations

import pathlib

from PIL import Image, ImageDraw

SIZE = 256
SUPERSAMPLE = 4  # PIL does not antialias; draw big and downsample instead.

DISC = (14, 14, 14, 225)
LIGHT = (255, 255, 255, 255)

RINGS = {
    "ai_generated": (255, 255, 255, 255),
    "ai_manipulated": (245, 166, 35, 255),
    "ai_composite": (74, 197, 232, 255),
    "unknown": (168, 168, 168, 255),
}

OUT = pathlib.Path(__file__).resolve().parent.parent / "src" / "thumbor_ai_label" / "icons"


def draw_a(draw, box, width, colour):
    x0, y0, x1, y1 = box
    apex = ((x0 + x1) / 2, y0)
    draw.line([ (x0, y1), apex ], fill=colour, width=width, joint="curve")
    draw.line([ apex, (x1, y1) ], fill=colour, width=width, joint="curve")
    bar_y = y0 + (y1 - y0) * 0.68
    inset = (x1 - x0) * 0.19
    draw.line([(x0 + inset, bar_y), (x1 - inset, bar_y)], fill=colour, width=width)


def draw_i(draw, box, width, colour):
    x0, y0, x1, y1 = box
    x = (x0 + x1) / 2
    draw.line([(x, y0), (x, y1)], fill=colour, width=width)


def draw_question(draw, box, width, colour):
    x0, y0, x1, y1 = box
    span = x1 - x0
    # Upper hook, drawn as an arc so no curve data has to be hand-fitted.
    draw.arc([x0, y0, x1, y0 + span], start=170, end=20, fill=colour, width=width)
    # Stem down from where the hook ends, then the dot.
    mid = (x0 + x1) / 2
    draw.line([(mid, y0 + span * 0.62), (mid, y1 - span * 0.34)], fill=colour, width=width)
    dot = span * 0.14
    draw.ellipse([mid - dot, y1 - dot * 2, mid + dot, y1], fill=colour)


def build(state: str) -> Image.Image:
    scale = SUPERSAMPLE
    canvas = SIZE * scale
    image = Image.new("RGBA", (canvas, canvas), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    inset = 6 * scale
    ring_width = 13 * scale
    draw.ellipse([inset, inset, canvas - inset, canvas - inset], fill=DISC)

    ring_box = [
        inset + ring_width / 2,
        inset + ring_width / 2,
        canvas - inset - ring_width / 2,
        canvas - inset - ring_width / 2,
    ]
    ring = RINGS[state]

    if state == "ai_composite":
        # A split ring reads as "partly" even in greyscale, where the colour
        # difference from ai_generated would vanish.
        for start, end in ((205, 335), (25, 155)):
            draw.arc(ring_box, start=start, end=end, fill=ring, width=ring_width)
    else:
        draw.ellipse(ring_box, outline=ring, width=ring_width)

    stroke = 20 * scale
    if state == "unknown":
        box = [canvas * 0.34, canvas * 0.28, canvas * 0.66, canvas * 0.72]
        draw_question(draw, box, stroke, LIGHT)
    else:
        top, bottom = canvas * 0.33, canvas * 0.67
        draw_a(draw, [canvas * 0.26, top, canvas * 0.52, bottom], stroke, LIGHT)
        draw_i(draw, [canvas * 0.60, top, canvas * 0.74, bottom], stroke, LIGHT)

    if state == "ai_manipulated":
        # A solid wedge marks "edited" without relying on the ring colour.
        r = canvas * 0.13
        cx, cy = canvas * 0.79, canvas * 0.79
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=ring)
        draw.line(
            [(cx - r * 0.42, cy + r * 0.42), (cx + r * 0.42, cy - r * 0.42)],
            fill=(*DISC[:3], 255),
            width=int(7 * scale),
        )

    return image.resize((SIZE, SIZE), Image.LANCZOS)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for state in RINGS:
        path = OUT / f"{state}.png"
        build(state).save(path, "PNG", optimize=True)
        print(f"wrote {path.name} ({path.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
