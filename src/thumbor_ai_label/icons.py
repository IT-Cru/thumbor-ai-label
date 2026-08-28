"""Label icon sets: loading, overriding and caching.

Icons are loaded and validated once at startup, not per request. Scaled variants
are cached, because rescaling source artwork on every request would be the most
expensive thing this plugin does.

Four sets ship:

``default`` / ``default-light``
    This plugin's own marks, drawn by ``tools/make_icons.py``. ``default`` is a
    light glyph on a dark disc, for light imagery; ``default-light`` is the
    inverse, for dark imagery. Both stay legible down to 20 px.

``eu`` / ``eu-white``
    The European Commission's harmonised labels for AI-generated content, published
    10 June 2026 and free to use without attribution. ``eu`` is the dark-fill
    artwork for light imagery; ``eu-white`` is the inverse, for dark imagery. These
    are icon-plus-text lockups around 3:1, not squares.

The artwork itself lives in ``ai-labels/`` at the repository root rather than
under ``src/``: it is design source, regenerated and reviewed on its own cadence,
and downstream users fork it to make house-style sets. See ``_bundled_dir``.

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

#: In a wheel, ``pyproject.toml`` maps the repository's ``ai-labels/`` directory
#: to ``thumbor_ai_label/labelsets/``, so the artwork installs inside the package
#: and resolves next to this module.
_PACKAGED_DIR = pathlib.Path(__file__).resolve().parent / "labelsets"

#: In a checkout, there is no such directory: an editable install puts ``src`` on
#: the path and leaves the artwork where git has it. This is the live copy that
#: ``tools/make_icons.py`` writes, so contributors see their edits immediately.
_CHECKOUT_DIR = pathlib.Path(__file__).resolve().parent.parent.parent / "ai-labels"


#: Packaged location first, so a wheel that happens to be installed inside a
#: checkout still reads its own artwork rather than the working tree's.
_ICON_DIR_CANDIDATES = (_PACKAGED_DIR, _CHECKOUT_DIR)


def _bundled_dir(candidates: tuple[pathlib.Path, ...] = _ICON_DIR_CANDIDATES) -> pathlib.Path:
    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    # Neither exists, which means a broken install. Name the packaged location:
    # it is the one an operator hitting this can actually do something about.
    # IconSet then raises with the full path, rather than failing less obviously.
    return candidates[0]


DEFAULT_ICON_DIR = _bundled_dir()

DEFAULT_SET = "default"
BUNDLED_SETS = (DEFAULT_SET, "default-light", "eu", "eu-white")

#: Scaled variants held per icon set. Label size tracks output size, so a busy
#: server sees many distinct sizes; this bounds what that can cost.
RESIZE_CACHE_SIZE = 256


class IconError(Exception):
    """Raised at startup for an unusable icon configuration."""


def set_directory(name: str, base: pathlib.Path | None = None) -> pathlib.Path:
    """Directory holding one set's artwork.

    Every set, ``default`` included, is a subdirectory. That was not always true -
    ``default`` used to sit loose in the icon root - and making it uniform is what
    lets an operator point ``AI_LABEL_ICON_DIR`` at a directory of their own house
    sets and have them resolve exactly like the bundled ones.

    ``base`` replaces the bundled directory rather than extending it. There is no
    search across both: a mistyped house-style name has to fail, because falling
    back would ship this plugin's default marks under the operator's name - a wrong
    label rather than a missing one.
    """
    base = pathlib.Path(base) if base else DEFAULT_ICON_DIR
    return base / name


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
        # Normalised once, so the lookup below and the error it may raise cannot
        # disagree about whether a base directory was configured.
        base = pathlib.Path(icon_dir) if icon_dir else None
        self._dir = set_directory(icon_set, base)

        if not self._dir.is_dir():
            # Which directory was searched is the whole of the diagnosis here, and it
            # is the one thing the old message left out: with AI_LABEL_ICON_DIR set,
            # "unknown icon set 'eu'" reads as a broken install rather than as a set
            # that was never copied into the mounted volume.
            if base is None:
                raise IconError(
                    "unknown icon set {!r} ({} does not exist); bundled sets are {}. "
                    "To draw your own artwork, put its set directories somewhere and "
                    "name that directory in AI_LABEL_ICON_DIR.".format(
                        icon_set, self._dir, ", ".join(BUNDLED_SETS)
                    )
                )
            raise IconError(
                "unknown icon set {!r} ({} does not exist); sets resolve as "
                "subdirectories of AI_LABEL_ICON_DIR ({}), and while that is set the "
                "bundled names ({}) do not resolve - copy the set in, or unset "
                "AI_LABEL_ICON_DIR to use the bundled artwork.".format(
                    icon_set, self._dir, base, ", ".join(BUNDLED_SETS)
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

        # Any falsy value used to fall through to the bundled icon, so an operator
        # writing {"unknown": ""} - or False, which reads as an off switch - silently
        # got the default mark. A map of paths holds paths; suppression lives in
        # AI_LABEL_DRAW_STATES.
        unusable = {
            key: value
            for key, value in overrides.items()
            if not isinstance(value, str | pathlib.Path) or not str(value).strip()
        }
        if unusable:
            raise IconError(
                "unusable icon override for {}; a path is required. To leave a state "
                "unmarked, drop it from AI_LABEL_DRAW_STATES instead.".format(
                    ", ".join(f"{key!r} = {value!r}" for key, value in sorted(unusable.items()))
                )
            )

        # Every remaining value is an explicit path, so nothing downstream needs a
        # truthiness test that could reintroduce the fallback. Stripping here keeps a
        # padded path from failing as a puzzling "not found" on an invisible space.
        paths = {key: pathlib.Path(str(value).strip()) for key, value in overrides.items()}

        self._icons: dict[SourceType, Image.Image] = {}
        for state in LABEL_STATES:
            self._icons[state] = self._load(state, paths.get(state.value))

        self._scaled = lru_cache(maxsize=RESIZE_CACHE_SIZE)(self._scale)

    def _load(self, state: SourceType, override: pathlib.Path | None) -> Image.Image:
        path = override if override is not None else self._dir / f"{state.value}.png"

        if not path.is_file():
            if override is not None:
                raise IconError(f"icon override for {state.value!r} not found: {path}")
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
