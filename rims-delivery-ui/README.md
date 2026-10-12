# RIMs Delivery: frontend

React + TypeScript + Vite + Tailwind. Customer quote flow at `/`, admin app at `/admin` (code-split, separate chunks).

## Run

    npm install
    cp .env.example .env.local   # set VITE_USE_MOCKS=true to run without a backend
    npm run dev                  # http://localhost:5173
    npm run build                # typecheck + production build

With `VITE_USE_MOCKS=true` a banner appears and a scenario picker lets you trigger every error state.
Mock names and amounts are placeholders, not RIMs data. Mock admin login accepts any credentials.
With mocks off, requests go to `VITE_API_BASE_URL` (default `/api/v1`, proxied to `localhost:8000` in dev).

## Principles

- The backend pricing engine is the only source of fees. No price, rate or destination is defined in this codebase.
- A fee is shown only when the quote is `completed`/`accepted` and has a destination, a distance and an amount above 0. Anything else shows an error or manual-review state.
- Calculation steps are rendered exactly as the API reports them (`steps[].state`). Nothing is shown complete unless the backend says so.
- The customer endpoints return no pricing breakdown. Breakdown is admin-only (`/admin/quotes/:id`).
- Map provider is isolated: `src/components/map/types.ts` is the contract, `providers/leaflet.tsx` the only implementation. Swap the lazy import in `MapPicker.tsx` to change provider. Geocoding and routing are backend calls, so no provider keys live in the browser.
- Auth is an httpOnly session cookie from the backend. The route guard is UX only; the API must authorise every admin call.
- To change brand colours, edit the RGB tokens at the top of `src/index.css`.

## API contract the frontend expects (FastAPI)

Errors: `{ "code": "<ErrorCode>", "message": "...", "details": {...} }` (codes in `src/types`). `401` on admin routes triggers the session-expired dialog.

| Method | Path | Notes |
|---|---|---|
| GET | `/public/config` | company, contact, dispatch point, map defaults |
| GET | `/public/locations/search?q=` | `GeoLocation[]` |
| GET | `/public/locations/reverse?lat=&lng=` | `GeoLocation`, or `INVALID_LOCATION` / `LOCATION_NOT_FOUND` |
| POST | `/public/quotes` | `{position,label,locationId?,reference?}` returns `Quote` (usually `processing`). `AMBIGUOUS_LOCATION` may include `details.candidates` |
| GET | `/public/quotes/{id}` | polled every second while `processing`; includes `steps[]`, `failure` |
| POST | `/public/quotes/{id}/recalculate` | returns `Quote` |
| POST | `/public/quotes/{id}/accept` | returns `Quote` with `status: accepted` |
| POST | `/auth/login`, `/auth/logout`, `/auth/me` | cookie session |
| GET | `/admin/dashboard` | `DashboardSummary` |
| GET | `/admin/quotes`, `/admin/quotes/{id}` | filters: search, status, destinationId, from, to, page, pageSize |
| GET/POST/PATCH | `/admin/destinations`, `/admin/pricing-rules`, `/admin/road-types`, `/admin/vehicles` | paged `{items,total,page,pageSize}`; deactivate via `PATCH {active:false}` |
| GET | `/admin/audit-log` | filters: entityType, search |
| GET/PATCH | `/admin/settings` | dispatch point, contact details |

## Decisions that need confirming

- "Continue" calls `accept` and shows a quote reference. If RIMs wants it to hand off to an order or WhatsApp step, change that one action.
- The customer never picks a vehicle or road type. The backend decides them. If vehicle depends on the order contents, the flow needs an order-size input.
- Pricing rule precedence (specific rule + priority wins) is described in the UI copy but enforced only by the backend.
