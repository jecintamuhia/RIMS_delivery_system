# RIMs brand assets for the cinematic opening

The full-screen introduction is built around the official RIMs logo and six
genuine photographs of the RIMs shop on Kenyatta Avenue, Naivasha. Drop the
files into this folder with the exact names below and the opening picks them
up automatically. Until an asset is present, the affected scene degrades to a
branded plate and the delivery calculator remains fully reachable.

## Assets

| File (drop into `public/brand/`) | Content | Status |
| --- | --- | --- |
| `rims-logo.png` | Official RIMs logo (transparent PNG) | supplied |
| `rims-logo.svg` | Optional vector version of the logo | optional |
| `rims-1.jpg` … `rims-6.jpg` | The six shop photographs used in the opening sequence | supplied |

The six photographs are shown full-bleed in order with a slow zoom (Ken Burns),
a cinematic darkening veil and a short caption, then hand over to the device
composition and the `START YOUR DELIVERY` action. Faces and any customers
should not be identifiable without consent.

## Where these are referenced

- `src/components/intro/assets.ts` — scene order, captions and filenames.
- `src/components/intro/CinematicIntro.tsx` — the timeline and logo fallbacks.
- `src/components/layout/Brand.tsx` — the header lockup (uses the API `logoUrl`).

The watermark in the header/intro can alternatively be configured server-side
by setting the `company_logo_url` system setting.