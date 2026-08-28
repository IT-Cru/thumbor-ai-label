# Label artwork

The icons the plugin draws onto images, one directory per set. Selected at runtime with
`AI_LABEL_ICON_SET`.

| Set | Marks | Intended for |
|---|---|---|
| `default` | this plugin's own | light imagery |
| `default-light` | this plugin's own | dark imagery |
| `eu` | European Commission, dark fill | light imagery |
| `eu-white` | European Commission, white fill | dark imagery |

Each set holds exactly four files — `ai_generated.png`, `ai_manipulated.png`,
`ai_composite.png`, `unknown.png`. There is deliberately no icon for `NOT_AI`: an image
positively identified as a camera photograph gets no label at all.

## These are generated. Do not hand-edit them.

| Set | Generator |
|---|---|
| `default/`, `default-light/` | `tools/make_icons.py` |
| `eu/`, `eu-white/` | `tools/fetch_eu_icons.py` |

The `default` sets are drawn from code so the design stays reviewable in a diff and
reproducible on any machine, with no font to ship or license. The `eu` sets are
downloaded from the Commission's published archive so their provenance stays checkable
rather than resting on trust in committed binaries.

`unknown.png` in the two `eu` directories is *this project's* neutral mark, copied from
`default/` and `default-light/` by `fetch_eu_icons.py`. It is not an EU icon, and that is
the point: the official marks assert content **is** AI, which is not a claim that can be
made about an image whose provenance merely could not be established.

## Licensing

The `default` sets are Apache-2.0, like the rest of this project. **The EU artwork is
not ours to relicense** — see [THIRD-PARTY.md](../THIRD-PARTY.md).

## Why this lives at the repository root

It is design source, reviewed and regenerated on its own cadence, and downstream users
fork it to build house styles — none of which is served by burying it under `src/`.
Wheels still need it beside the code that loads it, so `pyproject.toml` maps this
directory in as `thumbor_ai_label/labelsets/`. `thumbor_ai_label.icons` resolves
whichever of the two locations exists.

## House styles

Copy a set directory and edit the four PNGs, keeping the filenames. Then put the directory
holding it somewhere the server can reach — a mounted volume, not the installed package —
and name it:

```python
AI_LABEL_ICON_DIR = "/etc/thumbor/icon-sets"
AI_LABEL_ICON_SET = "house-style"
```

Your set resolves exactly like a bundled one. To swap a single mark instead of a whole
set, `AI_LABEL_ICONS` takes per-state paths.

While `AI_LABEL_ICON_DIR` is set, sets are looked up there and nowhere else: the bundled
names do not resolve, so a mistyped house-style name fails at boot rather than quietly
shipping these default marks. Copy a bundled set in if you want it alongside your own.

Everything is decoded once at startup, so a missing or corrupt file fails loudly at boot
rather than becoming a broken image mid-request.
