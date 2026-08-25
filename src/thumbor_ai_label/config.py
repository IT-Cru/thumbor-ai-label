"""Thumbor configuration keys, and resolving them into ready-to-use objects.

Importing this module registers the keys with Thumbor's config system.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from thumbor.config import Config

from .compose import Layout, Position
from .detect import Confidence, Detector, load_detectors
from .icons import BUNDLED_SETS, IconSet
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
    "AI_LABEL_ICON_SET",
    "default",
    "Which bundled icon set to draw: " + ", ".join(BUNDLED_SETS) + ". "
    "'eu' and 'eu-white' are the European Commission's harmonised AI labels; "
    "'eu' suits light imagery and 'eu-white' dark imagery.",
    GROUP,
)
Config.define(
    "AI_LABEL_ICONS",
    {},
    "Per-state icon overrides, e.g. {'ai_generated': '/etc/thumbor/icons/ai.png'}.",
    GROUP,
)
Config.define("AI_LABEL_OPACITY", 100, "Label opacity, 0-100.", GROUP)
Config.define(
    "AI_LABEL_POSITION",
    "bottom-right",
    "Label corner: top-left, top-right, bottom-left, bottom-right or center.",
    GROUP,
)
Config.define(
    "AI_LABEL_SIZE_RATIO", 0.14, "Label size as a fraction of the shorter edge.", GROUP
)
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

SETTINGS_ATTR = "_ai_label_settings"


@dataclass(frozen=True)
class Settings:
    """Config resolved once into the objects the request path needs."""

    enabled: bool
    detectors: List[Detector]
    policy: Policy
    min_confidence: Confidence
    icons: IconSet
    layout: Layout
    strict_errors: bool

    @classmethod
    def from_config(cls, config) -> "Settings":
        return cls(
            enabled=bool(config.AI_LABEL_ENABLED),
            detectors=load_detectors(config.AI_LABEL_DETECTORS),
            policy=Policy(str(config.AI_LABEL_POLICY).lower()),
            min_confidence=Confidence(str(config.AI_LABEL_MIN_CONFIDENCE).lower()),
            icons=IconSet(
                overrides=config.AI_LABEL_ICONS or {},
                opacity=int(config.AI_LABEL_OPACITY),
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
            strict_errors=bool(config.AI_LABEL_STRICT_ERRORS),
        )


def get_settings(config) -> Settings:
    """Resolve config once and reuse it.

    Config is shared for the life of the process, so icons are decoded and
    detectors resolved a single time rather than per request.
    """
    cached: Optional[Settings] = getattr(config, SETTINGS_ATTR, None)
    if cached is None:
        cached = Settings.from_config(config)
        setattr(config, SETTINGS_ATTR, cached)
    return cached
