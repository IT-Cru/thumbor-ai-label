"""Expose the provenance verdict on Thumbor's /meta/ endpoint.

This is a compliance feature, not a convenience. EU AI Act Article 50(5) requires
the disclosure to meet accessibility requirements, and the Commission asks
implementers to surface it through alt text or ARIA. A label burnt into pixels is
invisible to a screen reader, and Thumbor serves images - it does not control the
surrounding markup. This endpoint is how whatever writes that markup finds out.

Thumbor builds the meta response in ``JSONEngine.read()``, which offers no hook, so
the handler wraps ``_load_results`` and the verdict is merged into the serialised
payload here. That is a JSON round-trip rather than a string splice, so a change in
Thumbor's own payload cannot corrupt it.

``_load_results`` runs in Thumbor's thread pool, off the event loop, so nothing here
may await. The verdict is therefore read from where the filter already stored it; the
handler makes sure it exists before the response is assembled.
"""

from __future__ import annotations

import json

from thumbor.utils import logger

from .compose import fit_label
from .config import get_settings
from .detect import SourceType
from .policy import Decision, Reason
from .state import get_decision

#: Key the verdict is published under. A sibling of "thumbor" rather than a member of
#: it: this is not Thumbor's namespace, and a future Thumbor key must not be able to
#: collide with ours.
PAYLOAD_KEY = "ai_label"

#: Human-readable disclosure per state, for alt text or an ARIA label. English by
#: default and overridable through AI_LABEL_META_DISCLOSURES - a German publisher
#: needs German. Consumers wanting full control should map the machine-readable
#: `label` field themselves and ignore this one.
DEFAULT_DISCLOSURES = {
    SourceType.AI_GENERATED.value: "AI generated",
    SourceType.AI_MANIPULATED.value: "AI modified",
    SourceType.AI_COMPOSITE.value: "AI modified",
    # Deliberately not phrased as an AI claim. Unproven provenance is not evidence
    # of AI, and saying otherwise here would mislead exactly the users who cannot
    # see the image to judge for themselves.
    SourceType.UNKNOWN.value: "Image provenance could not be established",
}


def _would_draw(context, decision: Decision, target: tuple[int, int] | None) -> bool | None:
    """Whether an image request at these dimensions would carry a visible label.

    The distinction matters: below the minimum size no label is drawn, so the DOM
    disclosure becomes the *only* disclosure rather than a supplement to it.
    """
    if not decision.should_label or not target:
        return False
    try:
        settings = get_settings(context.config)
        aspect = settings.icons.aspect(decision.state)
        icon_size = (max(1, round(aspect * 1000)), 1000)
        return fit_label(target, icon_size, settings.layout) is not None
    except Exception:  # noqa: BLE001 - report unknown rather than guess at the answer
        logger.exception("[AiLabel] could not determine whether a label would be drawn")
        return None


def build_payload(context, decision: Decision, target=None) -> dict:
    """The object published under `ai_label`."""
    settings = get_settings(context.config)
    verbose = bool(getattr(context.config, "AI_LABEL_META_VERBOSE", False))

    disclosures = dict(DEFAULT_DISCLOSURES)
    disclosures.update(getattr(context.config, "AI_LABEL_META_DISCLOSURES", None) or {})

    full = decision.as_dict()
    payload = {
        "label": full["label"],
        "reason": full["reason"],
        "policy": settings.policy.value,
        "labelled": _would_draw(context, decision, target),
    }
    if decision.state is not None:
        payload["disclosure"] = disclosures.get(decision.state.value)

    if verbose:
        # Off by default: `evidence` can carry a fragment of a generation prompt
        # lifted from EXIF UserComment, and this endpoint is publicly reachable.
        for key in ("detector", "confidence", "evidence", "generator"):
            if key in full:
                payload[key] = full[key]

    return payload


def _unwrap_jsonp(body: str, callback: str | None) -> tuple[str, str, str]:
    """Split `cb({...});` into its parts. Returns ("", body, "") for plain JSON."""
    if callback:
        prefix, suffix = f"{callback}(", ");"
        if body.startswith(prefix) and body.endswith(suffix):
            return prefix, body[len(prefix) : -len(suffix)], suffix
    return "", body, ""


def inject(context, results):
    """Merge the verdict into a serialised meta response.

    Never raises and never returns something unparseable: on any failure the
    original response is handed back untouched. A broken labelling feature must not
    break an endpoint clients rely on.
    """
    try:
        if not getattr(context.config, "AI_LABEL_META", True):
            return results

        body = results.decode("utf-8") if isinstance(results, bytes) else results
        if not isinstance(body, str):
            return results

        # getattr twice: a Context that has not been through the request pipeline has
        # no `request` attribute at all, and reaching for it raises rather than
        # returning None.
        request = getattr(context, "request", None)
        callback = getattr(request, "meta_callback", None)
        prefix, payload_text, suffix = _unwrap_jsonp(body, callback)

        document = json.loads(payload_text)
        if not isinstance(document, dict):
            return results

        # Cannot await here - this runs in a worker thread. The handler guarantees a
        # verdict exists by now; if one somehow does not, say so rather than implying
        # the image was examined and found clean.
        decision = get_decision(context) or Decision(None, Reason.DETECTION_DISABLED)

        target = None
        engine = getattr(request, "engine", None)
        if engine is not None and hasattr(engine, "get_target_dimensions"):
            target = engine.get_target_dimensions()

        document[PAYLOAD_KEY] = build_payload(context, decision, target)
        merged = prefix + json.dumps(document) + suffix
        return merged.encode("utf-8") if isinstance(results, bytes) else merged
    except Exception:  # noqa: BLE001 - a broken feature must not break an endpoint clients rely on
        logger.exception("[AiLabel] could not add the verdict to the meta response")
        return results
