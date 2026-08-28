"""Generate the default label icon sets.

The icons are drawn from code rather than committed as opaque binaries so the
design is reviewable and reproducible. Run after changing anything here:

    python tools/make_icons.py

Writes ``ai-labels/default/`` (light glyph on a dark disc, for light imagery) and
``ai-labels/default-light/`` (the inverse, for dark imagery).

Design constraints, in priority order:

1. Legible at ~32 px, which is where most of these will actually be seen, and
   still identifiable at 20 px, the smallest label the plugin will draw.
2. Readable over any underlying image - hence an opaque disc behind the glyph,
   rather than a glyph laid directly on unknown pixels.
3. No font dependency. Glyphs are drawn as strokes, so output is identical on
   every machine and no font file has to be shipped or licensed.
4. Differentiated by more than colour, so the set survives greyscale printing and
   does not rely on colour vision.

On constraint 4: the state cue is the *shape of the ring*, because a ring's break
pattern is the only feature that reliably survives a downscale to 20 px. Gaps are
a full 90 deg or more - on a 20 px icon the ring's circumference is only ~50 px,
so anything narrower closes up. An earlier revision used a small badge glyph and
50 deg ring gaps; both dissolved into noise below 32 px.
"""

from __future__ import annotations

import math
import pathlib

from PIL import Image, ImageDraw

SIZE = 256
SUPERSAMPLE = 4  # PIL does not antialias; draw big and downsample instead.

OUT = pathlib.Path(__file__).resolve().parent.parent / "ai-labels"

#: Ring arcs per state, as (start, end) angle pairs in PIL's convention
#: (0 deg = 3 o'clock, increasing clockwise). The silhouettes are deliberately
#: far apart: a closed ring, a horseshoe open at the bottom, and two arcs facing
#: each other across open sides.
RINGS = {
    "ai_generated": ((0, 360),),
    "ai_manipulated": ((135, 45),),
    "ai_composite": ((200, 340), (20, 160)),
    "unknown": ((0, 360),),
}


class Palette:
    """One variant's colours.

    ``disc`` is slightly translucent so a label never looks like a sticker pasted
    over the photograph, but stays opaque enough to guarantee glyph contrast.
    """

    def __init__(self, name, disc, glyph, rings):
        self.name = name
        self.disc = disc
        self.glyph = glyph
        self.rings = rings


DARK = Palette(
    "default",
    disc=(14, 14, 14, 225),
    glyph=(255, 255, 255, 255),
    rings={
        "ai_generated": (255, 255, 255, 255),
        "ai_manipulated": (247, 176, 55, 255),
        "ai_composite": (90, 204, 236, 255),
        "unknown": (208, 208, 208, 255),
    },
)

#: Ring hues are darkened rather than reused: the dark set's amber and cyan are
#: tuned for contrast against near-black and fall below 3:1 on near-white.
LIGHT = Palette(
    "default-light",
    disc=(250, 250, 250, 232),
    glyph=(18, 18, 18, 255),
    rings={
        "ai_generated": (18, 18, 18, 255),
        "ai_manipulated": (176, 98, 0, 255),
        "ai_composite": (0, 116, 153, 255),
        "unknown": (105, 105, 105, 255),
    },
)


def draw_a(draw, box, width, colour):
    """A capital A as two strokes and a crossbar."""
    x0, y0, x1, y1 = box
    apex = ((x0 + x1) / 2, y0)
    draw.line([(x0, y1), apex], fill=colour, width=width, joint="curve")
    draw.line([apex, (x1, y1)], fill=colour, width=width, joint="curve")
    bar_y = y0 + (y1 - y0) * 0.68
    inset = (x1 - x0) * 0.19
    draw.line([(x0 + inset, bar_y), (x1 - inset, bar_y)], fill=colour, width=width)


def draw_i(draw, box, width, colour):
    x0, y0, x1, y1 = box
    x = (x0 + x1) / 2
    draw.line([(x, y0), (x, y1)], fill=colour, width=width)


def question_spine(box):
    """Points tracing a question mark's bowl, neck and stem as one open path.

    Returned as a single polyline rather than an arc plus a separate line: the
    previous revision drew the bowl with ``ImageDraw.arc`` and the stem with
    ``ImageDraw.line``, and because the bowl's lower-right terminal sits well
    right of centre while the stem was centred, the two never met. The glyph read
    as a hook floating above a bar. Sampling one continuous path cannot detach.
    """
    x0, y0, x1, y1 = box
    span = x1 - x0

    radius = span * 0.5
    cx = (x0 + x1) / 2
    cy = y0 + radius

    # Bowl: 8 o'clock clockwise over the top to 4:30, where the neck takes over.
    points = []
    angle = 145.0
    while angle <= 405.0:
        rad = math.radians(angle)
        points.append((cx + radius * math.cos(rad), cy + radius * math.sin(rad)))
        angle += 5.0

    # Neck: ease from the bowl's terminal back to centre, so the stem hangs
    # under the glyph's optical middle the way a drawn question mark does.
    stem_top = (cx, cy + radius * 1.02)
    start = points[-1]
    for step in range(1, 7):
        t = step / 6
        # Quadratic ease keeps the tangent continuous with the bowl.
        ease = t * t
        points.append(
            (
                start[0] + (stem_top[0] - start[0]) * ease,
                start[1] + (stem_top[1] - start[1]) * t,
            )
        )

    points.append((cx, y1 - span * 0.30))
    return points


def draw_question(draw, box, width, colour):
    x0, _, x1, y1 = box
    span = x1 - x0
    draw.line(question_spine(box), fill=colour, width=width, joint="curve")
    # Dot, set a clear stroke-width below the stem so the two never merge.
    dot = span * 0.115
    cx = (x0 + x1) / 2
    cy = y1 - dot
    draw.ellipse([cx - dot, cy - dot, cx + dot, cy + dot], fill=colour)


def build(state: str, palette: Palette) -> Image.Image:
    scale = SUPERSAMPLE
    canvas = SIZE * scale
    image = Image.new("RGBA", (canvas, canvas), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    inset = 6 * scale
    ring_width = 12 * scale
    draw.ellipse([inset, inset, canvas - inset, canvas - inset], fill=palette.disc)

    half = ring_width / 2
    ring_box = [inset + half, inset + half, canvas - inset - half, canvas - inset - half]
    ring = palette.rings[state]

    for start, end in RINGS[state]:
        if (start, end) == (0, 360):
            draw.ellipse(ring_box, outline=ring, width=ring_width)
        else:
            draw.arc(ring_box, start=start, end=end, fill=ring, width=ring_width)

    stroke = int(19 * scale)
    if state == "unknown":
        box = [canvas * 0.355, canvas * 0.255, canvas * 0.645, canvas * 0.745]
        draw_question(draw, box, stroke, palette.glyph)
    else:
        top, bottom = canvas * 0.31, canvas * 0.69
        draw_a(draw, [canvas * 0.245, top, canvas * 0.515, bottom], stroke, palette.glyph)
        draw_i(draw, [canvas * 0.60, top, canvas * 0.755, bottom], stroke, palette.glyph)

    return image.resize((SIZE, SIZE), Image.LANCZOS)


def main():
    for palette in (DARK, LIGHT):
        out = OUT / palette.name
        out.mkdir(parents=True, exist_ok=True)
        for state in RINGS:
            path = out / f"{state}.png"
            build(state, palette).save(path, "PNG", optimize=True)
            print(f"wrote {palette.name}/{path.name} ({path.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
