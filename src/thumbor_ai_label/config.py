"""Thumbor configuration keys, and resolving them into ready-to-use objects.

Importing this module registers the keys with Thumbor's config system.
"""

from __future__ import annotations

import pathlib
from dataclasses import dataclass

from thumbor.config import Config

from .compose import Layout, Position
from .detect import Confidence, Detector, SourceType, load_detectors
from .icons import BUNDLED_SETS, LABEL_STATES, IconSet
from .policy import Policy

GROUP = "AI Label"

Config.define("AI_LABEL_ENABLED", True, "Draw AI labels on generated images.", GROUP)
Config.define(
    "AI_LABEL_DETECTORS",
    None,
    "Ordered list of detector names. None uses the built-in default order.",
    GROUP,
)
Config.define(
    "AI_LABEL_POLICY",
    "strict",
    "What to do when nothing asserts how the image was made. 'strict' labels "
    "anything without a positive not-AI assertion; 'relaxed' labels only images "
    "carrying a provenance-capable block that says nothing conclusive.",
    GROUP,
)
Config.define(
    "AI_LABEL_MIN_CONFIDENCE",
    "low",
    "Lowest detector confidence that may raise an AI label: low, medium or high.",
    GROUP,
)
Config.define(
    "AI_LABEL_ICON_DIR",
    None,
    "Directory holding icon sets, one subdirectory per set, for a house style that "
    "ships as a mounted volume rather than as edits inside the installed package. "
    "None uses the bundled artwork. While this is set the bundled set names do not "
    "resolve: a set is looked up here and nowhere else.",
    GROUP,
)
Config.define(
    "AI_LABEL_ICON_SET",
    "default",
    "Which icon set to draw. Bundled: " + ", ".join(BUNDLED_SETS) + ". "
    "'default' and 'default-light' are this plugin's own marks; "
    "'eu' and 'eu-white' are the European Commission's harmonised AI labels. "
    "The plain names suit light imagery and the light/white ones dark imagery. "
    "With AI_LABEL_ICON_DIR set, this names a subdirectory of that instead.",
    GROUP,
)
Config.define(
    "AI_LABEL_ICONS",
    {},
    "Per-state icon overrides, e.g. {'ai_generated': '/etc/thumbor/icons/ai.png'}.",
    GROUP,
)
Config.define(
    "AI_LABEL_DRAW_STATES",
    None,
    "Which label states get a visible mark, e.g. ['ai_generated', 'ai_manipulated', "
    "'ai_composite'] to leave 'unknown' unmarked. None draws all of them. A state left "
    "out is still detected and still reported on /meta/, with 'labelled': false - so the "
    "disclosure a CMS writes into the DOM becomes the only one for those images.",
    GROUP,
)
Config.define("AI_LABEL_OPACITY", 100, "Label opacity, 0-100.", GROUP)
Config.define(
    "AI_LABEL_POSITION",
    "bottom-right",
    "Label corner: top-left, top-right, bottom-left, bottom-right or center.",
    GROUP,
)
Config.define("AI_LABEL_SIZE_RATIO", 0.14, "Label size as a fraction of the shorter edge.", GROUP)
Config.define("AI_LABEL_MIN_SIZE", 20, "Smallest label, in pixels.", GROUP)
Config.define("AI_LABEL_MAX_SIZE", 96, "Largest label, in pixels.", GROUP)
Config.define(
    "AI_LABEL_MIN_IMAGE_SIZE",
    120,
    "Images whose shorter edge is below this get no label at all.",
    GROUP,
)
Config.define(
    "AI_LABEL_MARGIN_RATIO", 0.04, "Label margin as a fraction of the shorter edge.", GROUP
)
Config.define("AI_LABEL_MIN_MARGIN", 3, "Smallest label margin, in pixels.", GROUP)
Config.define(
    "AI_LABEL_STRICT_ERRORS",
    False,
    "Raise instead of serving an unlabelled image when labelling fails. Off by default: "
    "one bad icon path should not take down image delivery.",
    GROUP,
)

Config.define(
    "AI_LABEL_META",
    True,
    "Publish the provenance verdict on Thumbor's /meta/ endpoint, under an "
    "'ai_label' key. This is how a CMS obtains the verdict to write alt text or an "
    "ARIA label, which is what EU AI Act Article 50(5) accessibility asks for.",
    GROUP,
)
Config.define(
    "AI_LABEL_META_VERBOSE",
    False,
    "Include detector, confidence, evidence and generator in the meta payload. Off "
    "by default: evidence can carry a fragment of a generation prompt read out of "
    "EXIF UserComment, and the meta endpoint is publicly reachable.",
    GROUP,
)
Config.define(
    "AI_LABEL_META_DISCLOSURES",
    None,
    "Override the human-readable disclosure strings per state, e.g. "
    "{'ai_generated': 'KI-generiert'}. None uses the English defaults.",
    GROUP,
)


def parse_icon_dir(value) -> pathlib.Path | None:
    """Resolve ``AI_LABEL_ICON_DIR`` into a base directory, or ``None`` for bundled.

    Both this and ``AI_LABEL_ICON_SET`` are plain strings, which is the point of the
    key: unlike the dict-valued ``AI_LABEL_ICONS``, a whole house set can be named
    from a container's environment. So the empty string an unrendered template
    variable leaves behind has to read as "not configured" rather than as a set
    directory called ``""``, which would resolve relative to the working directory.
    """
    if value is None:
        return None
    text = str(value).strip()
    return pathlib.Path(text) if text else None


def parse_draw_states(value) -> frozenset[SourceType]:
    """Resolve ``AI_LABEL_DRAW_STATES`` into the states that get a visible mark.

    ``None`` means all of them: dropping a state weakens the disclosure an image
    carries, so it has to be an explicit act and never a default.

    A comma-separated string is accepted as well as a list, because a value passed
    through the environment arrives as a string - derpconf hands environment values
    over unparsed - and this key is one an operator will reasonably want to set from
    a container's environment.
    """
    if value is None:
        return frozenset(LABEL_STATES)

    if isinstance(value, str):
        # An empty string is an unset template variable, not a request to stop
        # labelling everything. Read it as "not configured".
        if not value.strip():
            return frozenset(LABEL_STATES)
        names = [part.strip() for part in value.split(",") if part.strip()]
    else:
        names = [str(name).strip() for name in value]

    valid = {state.value: state for state in LABEL_STATES}
    states = set()
    for name in names:
        state = valid.get(name.lower())
        if state is None:
            raise ValueError(
                "unknown label state {!r} in AI_LABEL_DRAW_STATES; drawable states are {}".format(
                    name, ", ".join(valid)
                )
            )
        states.add(state)
    return frozenset(states)


SETTINGS_ATTR = "_ai_label_settings"


@dataclass(frozen=True)
class Settings:
    """Config resolved once into the objects the request path needs."""

    enabled: bool
    detectors: list[Detector]
    policy: Policy
    min_confidence: Confidence
    icons: IconSet
    layout: Layout
    draw_states: frozenset[SourceType]
    strict_errors: bool

    @classmethod
    def from_config(cls, config) -> Settings:
        return cls(
            enabled=bool(config.AI_LABEL_ENABLED),
            detectors=load_detectors(config.AI_LABEL_DETECTORS),
            policy=Policy(str(config.AI_LABEL_POLICY).lower()),
            min_confidence=Confidence(str(config.AI_LABEL_MIN_CONFIDENCE).lower()),
            icons=IconSet(
                overrides=config.AI_LABEL_ICONS or {},
                opacity=int(config.AI_LABEL_OPACITY),
                icon_dir=parse_icon_dir(config.AI_LABEL_ICON_DIR),
                icon_set=str(config.AI_LABEL_ICON_SET),
            ),
            layout=Layout(
                size_ratio=float(config.AI_LABEL_SIZE_RATIO),
                min_size=int(config.AI_LABEL_MIN_SIZE),
                max_size=int(config.AI_LABEL_MAX_SIZE),
                min_image_size=int(config.AI_LABEL_MIN_IMAGE_SIZE),
                position=Position(str(config.AI_LABEL_POSITION).lower()),
                margin_ratio=float(config.AI_LABEL_MARGIN_RATIO),
                min_margin=int(config.AI_LABEL_MIN_MARGIN),
            ),
            draw_states=parse_draw_states(config.AI_LABEL_DRAW_STATES),
            strict_errors=bool(config.AI_LABEL_STRICT_ERRORS),
        )

    def draws(self, state: SourceType | None) -> bool:
        """Whether ``state`` gets a visible mark.

        Both the draw path and the meta endpoint ask this one question, so what the
        pixels carry and what ``/meta/`` reports cannot drift apart.
        """
        return state is not None and state in self.draw_states


def get_settings(config) -> Settings:
    """Resolve config once and reuse it.

    Config is shared for the life of the process, so icons are decoded and
    detectors resolved a single time rather than per request.
    """
    cached: Settings | None = getattr(config, SETTINGS_ATTR, None)
    if cached is None:
        cached = Settings.from_config(config)
        setattr(config, SETTINGS_ATTR, cached)
    return cached
