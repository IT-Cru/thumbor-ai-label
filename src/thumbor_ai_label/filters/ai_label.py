"""The ``ai_label`` filter.

Runs after the transform, so the label is sized against the final output rather
than the source. Add it to ``FILTERS`` to use it per URL; the always-on handler
injects it for every request.
"""

from __future__ import annotations

from thumbor.filters import PHASE_POST_TRANSFORM, BaseFilter, filter_method

from ..label import apply


class Filter(BaseFilter):
    phase = PHASE_POST_TRANSFORM

    @filter_method()
    async def ai_label(self):
        await apply(self.context, self.engine)
