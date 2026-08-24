"""Label geometry and compositing.

Separated from the filter so the sizing and placement rules can be tested as
arithmetic, without standing up a Thumbor request. No Thumbor import.

Labels are **not assumed to be square**. The official EU labels are icon-plus-text
lockups roughly 3:1, so size is driven by height and width follows from the icon's
own aspect ratio.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional, Tuple

from PIL import Image


class Position(str, Enum):
    TOP_LEFT = "top-left"
    TOP_RIGHT = "top-right"
    BOTTOM_LEFT = "bottom-left"
    BOTTOM_RIGHT = "bottom-right"
    CENTER = "center"


@dataclass(frozen=True)
class Layout:
    """How large the label is and where it sits.

    Sizes are expressed against the *shorter* edge so a label occupies the same
    visual weight on a panorama as on a square crop - scaling by width alone makes
    labels on wide images look tiny and on tall ones absurd.

    ``size_ratio``, ``min_size`` and ``max_size`` all describe the label's **height**.
    Width follows from the icon's aspect ratio, then gets reduced if it would not fit.
    """

    size_ratio: float = 0.14
    min_size: int = 20
    max_size: int = 96
    #: Below this shorter edge no label is drawn. A label on a 64 px thumbnail is
    #: an unreadable smudge that costs bytes and tells the viewer nothing.
    min_image_size: int = 120
    position: Position = Position.BOTTOM_RIGHT
    margin_ratio: float = 0.04
    min_margin: int = 3

    def __post_init__(self):
        if not 0 < self.size_ratio <= 1:
            raise ValueError("size_ratio must be in (0, 1], got {}".format(self.size_ratio))
        if not 0 <= self.margin_ratio < 0.5:
            raise ValueError("margin_ratio must be in [0, 0.5), got {}".format(self.margin_ratio))
        if self.min_size > self.max_size:
            raise ValueError(
                "min_size {} exceeds max_size {}".format(self.min_size, self.max_size)
            )
        if self.min_size < 1:
            raise ValueError("min_size must be positive, got {}".format(self.min_size))


def label_margin(image_size: Tuple[int, int], layout: Layout) -> int:
    shorter = min(image_size)
    return max(layout.min_margin, round(shorter * layout.margin_ratio))


def label_height(image_size: Tuple[int, int], layout: Layout) -> Optional[int]:
    """Label height in pixels, or None if this image is too small to label."""
    width, height = image_size
    if width < 1 or height < 1:
        return None

    shorter = min(width, height)
    if shorter < layout.min_image_size:
        return None

    size = round(shorter * layout.size_ratio)
    size = max(layout.min_size, min(layout.max_size, size))

    margin = label_margin(image_size, layout)
    available = height - 2 * margin
    if available < 1:
        return None
    return max(1, min(size, available))


def fit_label(
    image_size: Tuple[int, int], icon_size: Tuple[int, int], layout: Layout
) -> Optional[Tuple[int, int]]:
    """Final on-image label size, honouring the icon's aspect ratio.

    Height comes from the layout; width follows the icon. A wide lockup on a narrow
    image is then scaled down so it still fits inside its margins - squashing it to
    fit would deform an official mark.
    """
    icon_w, icon_h = icon_size
    if icon_w < 1 or icon_h < 1:
        return None

    height = label_height(image_size, layout)
    if height is None:
        return None

    width = max(1, round(icon_w * height / icon_h))

    margin = label_margin(image_size, layout)
    available_w = image_size[0] - 2 * margin
    if available_w < 1:
        return None

    if width > available_w:
        height = max(1, round(icon_h * available_w / icon_w))
        width = available_w

    return width, height


def label_origin(
    image_size: Tuple[int, int], label_size: Tuple[int, int], layout: Layout
) -> Tuple[int, int]:
    """Top-left corner for a label of ``label_size``."""
    width, height = image_size
    label_w, label_h = label_size
    margin = label_margin(image_size, layout)

    if layout.position is Position.CENTER:
        return (round((width - label_w) / 2), round((height - label_h) / 2))

    left = margin
    right = width - label_w - margin
    top = margin
    bottom = height - label_h - margin

    x = left if layout.position in (Position.TOP_LEFT, Position.BOTTOM_LEFT) else right
    y = top if layout.position in (Position.TOP_LEFT, Position.TOP_RIGHT) else bottom

    # Clamp so a label on a very lopsided image cannot land outside the frame.
    return (max(0, min(x, width - label_w)), max(0, min(y, height - label_h)))


def paste_label(image: Image.Image, icon: Image.Image, origin: Tuple[int, int]) -> Image.Image:
    """Composite ``icon`` onto ``image``, returning the image to use afterwards.

    Palette and greyscale images are promoted to RGB first: an antialiased label
    cannot be composited into a palette without one, and quietly drawing an
    aliased label instead would look broken. The promotion is returned rather than
    applied in place so the caller can see the mode changed.
    """
    if icon.mode != "RGBA":
        icon = icon.convert("RGBA")

    target = image
    if image.mode not in ("RGB", "RGBA"):
        has_alpha = image.mode in ("LA", "PA") or (
            image.mode == "P" and "transparency" in image.info
        )
        target = image.convert("RGBA" if has_alpha else "RGB")

    target.paste(icon, origin, icon)
    return target


def apply_label(
    image: Image.Image, icon_for_height, layout: Layout
) -> Tuple[Image.Image, bool]:
    """Size, place and paste a label. Returns (image, whether a label was drawn).

    ``icon_for_height`` is called with a pixel height and returns the icon at that
    height, preserving its own aspect ratio.
    """
    height = label_height(image.size, layout)
    if height is None:
        return image, False

    icon = icon_for_height(height)
    if icon is None:
        return image, False

    fitted = fit_label(image.size, icon.size, layout)
    if fitted is None:
        return image, False

    if icon.size != fitted:
        # Re-request at the corrected height so the scale happens from the source
        # artwork rather than from an already-downscaled copy.
        icon = icon_for_height(fitted[1])
        if icon.size != fitted:
            icon = icon.resize(fitted, Image.LANCZOS)

    origin = label_origin(image.size, icon.size, layout)
    return paste_label(image, icon, origin), True
