"""Label icon sets: loading, overriding and caching.

Icons are loaded and validated once at startup, not per request. Scaled variants
are cached, because rescaling source artwork on every request would be the most
expensive thing this plugin does.

Three sets ship:

``default``
    This plugin's own marks - a dark disc behind a light glyph, designed to stay
    legible over arbitrary imagery at small sizes.

``eu`` / ``eu-white``
    The European Commission's harmonised labels for AI-generated content, published
    10 June 2026 and free to use without attribution. ``eu`` is the dark-fill
    artwork for light imagery; ``eu-white`` is the inverse, for dark imagery. These
    are icon-plus-text lockups around 3:1, not squares.

No Thumbor import.
"""

from __future__ import annotations

import pathlib
from collections.abc import Mapping
from functools import lru_cache

from PIL import Image

from .detect import SourceType

#: States a label can be drawn for. NOT_AI is absent by design: a positively
#: identified camera photograph gets no label at all.
LABEL_STATES = (
    SourceType.AI_GENERATED,
    SourceType.AI_MANIPULATED,
    SourceType.AI_COMPOSITE,
    SourceType.UNKNOWN,
)

DEFAULT_ICON_DIR = pathlib.Path(__file__).resolve().parent / "icons"

DEFAULT_SET = "default"
BUNDLED_SETS = (DEFAULT_SET, "eu", "eu-white")

#: Scaled variants held per icon set. Label size tracks output size, so a busy
#: server sees many distinct sizes; this bounds what that can cost.
RESIZE_CACHE_SIZE = 256


class IconError(Exception):
    """Raised at startup for an unusable icon configuration."""


def set_directory(name: str, base: pathlib.Path | None = None) -> pathlib.Path:
    base = pathlib.Path(base) if base else DEFAULT_ICON_DIR
    return base if name == DEFAULT_SET else base / name


class IconSet:
    """The label icons for one set, with any configured overrides applied.

    Construction reads and decodes every icon, so a missing or corrupt override
    fails at boot rather than turning into a broken image mid-request.
    """

    def __init__(
        self,
        overrides: Mapping[str, str] | None = None,
        opacity: int = 100,
        icon_dir: pathlib.Path | None = None,
        icon_set: str = DEFAULT_SET,
    ):
        if not 0 <= opacity <= 100:
            raise IconError(f"opacity must be between 0 and 100, got {opacity}")

        self.opacity = opacity
        self.name = icon_set
        self._dir = set_directory(icon_set, icon_dir)

        if not self._dir.is_dir():
            raise IconError(
                "unknown icon set {!r} ({} does not exist); bundled sets are {}".format(
                    icon_set, self._dir, ", ".join(BUNDLED_SETS)
                )
            )

        overrides = dict(overrides or {})
        unknown_keys = set(overrides) - {state.value for state in LABEL_STATES}
        if unknown_keys:
            raise IconError(
                "unknown label states in icon overrides: {}; valid states are {}".format(
                    ", ".join(sorted(unknown_keys)),
                    ", ".join(state.value for state in LABEL_STATES),
                )
            )

        self._icons: dict[SourceType, Image.Image] = {}
        for state in LABEL_STATES:
            path = overrides.get(state.value)
            self._icons[state] = self._load(state, pathlib.Path(path) if path else None)

        self._scaled = lru_cache(maxsize=RESIZE_CACHE_SIZE)(self._scale)

    def _load(self, state: SourceType, override: pathlib.Path | None) -> Image.Image:
        path = override if override is not None else self._dir / f"{state.value}.png"

        if not path.is_file():
            if override is not None:
                raise IconError(
                    f"icon override for {state.value!r} not found: {path}"
                )
            raise IconError(f"icon set {self.name!r} is missing {path}")

        try:
            with Image.open(path) as handle:
                icon = handle.convert("RGBA")
        except Exception as exc:
            raise IconError(f"could not read icon {path}: {exc}") from exc

        if self.opacity < 100:
            alpha = icon.getchannel("A").point(lambda value: value * self.opacity // 100)
            icon.putalpha(alpha)

        return icon

    def _scale(self, state: SourceType, height: int) -> Image.Image:
        icon = self._icons[state]
        if icon.height == height:
            return icon
        width = max(1, round(icon.width * height / icon.height))
        return icon.resize((width, height), Image.LANCZOS)

    def get(self, state: SourceType, height: int) -> Image.Image:
        """The icon for ``state`` at ``height`` pixels, keeping its aspect ratio.

        Height rather than a square size: the EU labels are wide lockups, and
        forcing them into a square would deform an official mark.
        """
        if state not in self._icons:
            raise IconError(f"no icon for state {state!r}")
        if height < 1:
            raise IconError(f"icon height must be positive, got {height}")
        return self._scaled(state, height)

    def aspect(self, state: SourceType) -> float:
        icon = self._icons[state]
        return icon.width / icon.height

    def cache_info(self):
        return self._scaled.cache_info()
