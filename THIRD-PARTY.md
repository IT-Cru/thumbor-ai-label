# Third-party assets

Everything in this repository is licensed under Apache-2.0 (see [LICENSE](LICENSE))
except the files described here.

This file is deliberately **not** part of [NOTICE](NOTICE). Under Apache-2.0 §4(d) the
contents of a NOTICE file must be reproduced by every derivative work anyone
distributes — so NOTICE carries only the short statement that must travel, and the
explanatory detail lives here where it does not burden downstream users.

## European Commission AI labelling icons

**Files**

    src/thumbor_ai_label/icons/eu/{ai_generated,ai_manipulated,ai_composite}.png
    src/thumbor_ai_label/icons/eu-white/{ai_generated,ai_manipulated,ai_composite}.png

**Source**
<https://digital-strategy.ec.europa.eu/en/policies/eu-icons-labelling-ai-generated-content>

Published 10 June 2026 alongside the Code of Practice on Transparency of AI-Generated
Content.

**Terms.** The Commission makes these icons "publicly available for everyone to use
freely, without the need for attribution to the Commission or the AI Office." They are
not covered by this project's Apache-2.0 licence and are not the copyright of this
project's authors.

**Modifications.** None to the design. The only change is a proportional downscale to
256 px in height; the source files are around 7500 px wide, and labels render between
20 and 96 px. [`tools/fetch_eu_icons.py`](tools/fetch_eu_icons.py) regenerates them
from the Commission's published archive, so provenance stays checkable rather than
resting on trust in committed binaries.

**Two caveats from the Commission's own guidance.**

- Signatories of the Code of Practice must use these icons in accordance with its
  placement specifications.
- Use of these icons by non-signatories "should not be construed as signaling of their
  adherence to the code." Displaying them does not enrol you in anything, and does not
  claim that it does.

## Not third-party

`unknown.png` in both `eu/` and `eu-white/` is this project's own work under
Apache-2.0. It is deliberately not an EU icon: the official marks assert that content
**is** AI-generated, which is not a claim that can be made about an image whose
provenance merely could not be established. Looking visibly different from the official
labels is the point.
