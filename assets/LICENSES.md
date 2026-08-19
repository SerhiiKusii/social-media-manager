# Asset provenance

Everything that appears on screen has to be traceable to a licence. This
file is the human-readable record; the `assets` table is the machine one,
and `preflight()` blocks publishing anything whose row is not
`cleared_for_commercial`.

The pipeline never republishes scraped video (see
`src/trendstealer/render/props.py`), so this file plus the Pexels library
is the complete set of what can reach a render.

`assets/` contents are gitignored apart from this file -- media is not
committed. Re-fetch stock clips with `trendstealer assets fetch-pexels`.

## Stock B-roll

| Source | Licence | Commercial use | Attribution |
|---|---|---|---|
| Pexels (`assets/video/pexels-*.mp4`) | [Pexels License](https://www.pexels.com/license/) | Yes | Not required; recorded in `assets.attribution` anyway |

## Photos

| File | Licence status | Notes |
|---|---|---|
| `photos/carlos1.webp` | **User-asserted** | Carlos Valderrama press photo. Licence not verified. |
| `photos/carlos2.png` | **User-asserted** | Carlos Valderrama press photo. Licence not verified. |
| `photos/carlos3.webp` | **User-asserted** | Carlos Valderrama press photo. Licence not verified. |

The Carlos photos are marked `cleared_for_commercial = 1` on the account
owner's explicit instruction, who accepted responsibility for the usage.
This is a deliberate override, not evidence of a licence: these appear to
be professional agency photographs, and agency stills normally require a
paid licence for commercial use. Editorial or fan-account use is common
practice but is not the same thing as holding rights. Replace them with
owned or properly licensed images before this runs at any scale.
