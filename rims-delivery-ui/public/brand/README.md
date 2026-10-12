# RIMs brand assets for the cinematic opening

The full-screen introduction is built around the official RIMs logo and three
genuine photographs of the RIMs shop on Kenyatta Avenue, Naivasha. Drop the
files into this folder with the exact names below and the opening picks them
up automatically. Until an asset is present, the affected scene degrades to a
branded plate and the delivery calculator remains fully reachable.

## Required assets

| File (drop into `public/brand/`) | Content | Recommended source |
| --- | --- | --- |
| `rims-logo.svg` | Official RIMs logo, transparent background | Vector SVG preferred; a high-resolution PNG (≥ 1000px wide, transparent) also works |
| `rims-logo.png` | Same logo as a fallback (only needed if no SVG) | PNG-24, transparent, ≥ 1000px wide |
| `store-day.jpg` | The shop exterior in daylight | 2560×1440 (16:9) or wider, < 400 KB after optimisation |
| `store-night.jpg` | The same exterior at night | 2560×1440 (16:9) or wider, < 400 KB |
| `store-interior.jpg` | The shop interior with shelving/product | 2560×1440 (16:9) or wider, < 400 KB |

The three photographs are used as full-bleed backgrounds with a slow zoom
(Ken Burns) and a cinematic darkening veil, so keep the focal point central or
centre-right. Faces and any customers should not be identifiable without
consent. Anything lighter can be downsampled to 1600px wide.

## Where these are referenced

- `src/components/intro/assets.ts` — scene order, captions and filenames.
- `src/components/intro/CinematicIntro.tsx` — the timeline and logo fallbacks.
- `src/components/layout/Brand.tsx` — the header lockup (uses the API `logoUrl`).

The watermark in the header/intro can alternatively be configured server-side
by setting the `company_logo_url` system setting.