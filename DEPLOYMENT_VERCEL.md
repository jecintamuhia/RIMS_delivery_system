# Production deployment: Vercel (frontend) + managed API (backend)

Runbook for hosting the RIMs Delivery frontend on Vercel and the FastAPI backend on a managed
host (Render), on the custom domain `rimssuppliesandhardware.co.ke`. It complements
[DEPLOYMENT.md](DEPLOYMENT.md), which covers the self-hosted Docker Compose + Caddy path.

## Status: verified production state

The zero-cost cutover is complete. Verified against production on 2026-11-16:

- The frontend is live on `https://rims-delivery-ui.vercel.app` and on the custom domain, with
  the `/api/*` proxy reaching the API.
- The API is live on `https://api.rimssuppliesandhardware.co.ke` (Render Free, behind
  Cloudflare). `/health` is `ok`; `/ready` reports database/cache/pricing `ok`, the active version
  `RIMs Transport Costs`, and 78 destinations.
- The database is Neon Free (`neondb`, PostgreSQL 18.7). All 16 tables, 61 indexes, 21 foreign
  keys, both active pricing versions and the Alembic head (`e4a1d7c9b3f2`) were verified after
  restore; per-table content hashes match the old Render database exactly.
- A fixed quote (Olkaria) returns KES 5500 and a distance quote (Nairobi) returns 91.17 km x
  KES 150 = KES 13676. Both are persisted.
- A new live quote was found in Neon and absent from the old Render database, proving the cutover.
  The quote survived a Render service restart.
- CORS now passes for `https://rims-delivery-ui.vercel.app`: preflight returns HTTP 200 with the
  correct origin, methods, headers and credentials; GET and POST also return the CORS headers.
  The two custom-domain origins also pass.
- The existing admin account authenticates: login returns 200 with an `HttpOnly` + `Secure`
  session cookie, and `/auth/me` returns `role=admin` with a CSRF token. Credentials were read
  from the Render environment in memory for the test and were not printed or stored.
- Backend tests, type checks and linter pass locally.

The full zero-cost runbook, backup/restore procedure, limitations and rollback steps are in
[DEPLOYMENT_FREE.md](DEPLOYMENT_FREE.md).

The Render web service and the old Render database are both on the **Free** plan. The old database
is kept until `2026-11-18T10:05:13Z` as a rollback copy and can then be deleted.

## Architecture

The admin session cookie is `HttpOnly` + `SameSite=Lax`, and the frontend calls the API with
`credentials: "include"` (`backend/app/api/deps.py`, `rims-delivery-ui/src/services/api/client.ts`).
Browsers only send a `Lax` cookie on same-site requests, so the API must appear on the **same
origin** as the site. Vercel serves the SPA and reverse-proxies the API paths to the backend:

```
browser ─▶ https://rimssuppliesandhardware.co.ke        (Vercel: static SPA + proxy)
                 │  /api/*  ,  /health  ,  /ready   →   ▼
        https://api.rimssuppliesandhardware.co.ke        (Render: FastAPI + Neon PostgreSQL)
```

## How frontend requests reach the backend (verified)

- `rims-delivery-ui/src/config/env.ts` sets `apiBase = import.meta.env.VITE_API_BASE_URL ?? "/api/v1"`,
  so with no build variable the browser calls `/api/v1/...` on the site's own origin.
- `rims-delivery-ui/vercel.json` lists the proxy rewrites, in order:

  | Source | Destination |
  | --- | --- |
  | `/api/:path*` | `https://api.rimssuppliesandhardware.co.ke/api/:path*` |
  | `/health` | `https://api.rimssuppliesandhardware.co.ke/health` |
  | `/ready` | `https://api.rimssuppliesandhardware.co.ke/ready` |
  | `/(.*)` | `/index.html` (SPA fallback) |

- The destination is a **concrete hostname, not a placeholder**. Vercel filesystem handling runs
  before rewrites, so the catch-all never shadows built assets.
- **Configurability:** Vercel `rewrites` are static config and cannot read environment variables
  (only the newer `routes` format can, and that has an open bug when mixed with `rewrites`). So
  the API origin is committed in this one file. If your API hostname differs, edit the three
  `api.rimssuppliesandhardware.co.ke` destinations and redeploy - that is the only change.

## Frontend build-time variables (verified: none required)

- The app defaults to the same-origin API base; no `VITE_*` variable is required to build or run.
- Do **not** set `VITE_API_BASE_URL` unless you deliberately point the SPA at a different API.
- Do **not** set `VITE_USE_MOCKS` - mocks return non-pricing data and are development-only.
- Never put secrets in `VITE_*` variables: they are compiled into the client bundle.

## Step 1 - Backend on Render

`render.yaml` (repo root) defines the legacy paid service + database. For a permanent KES 0/month
deployment use `render.free.yaml` with an external Neon database; see
[DEPLOYMENT_FREE.md](DEPLOYMENT_FREE.md). You can apply either as a Blueprint or create the
resources by hand with the same settings.

| Setting | Value |
| --- | --- |
| Runtime | Docker |
| Dockerfile path | `backend/Dockerfile` (relative to repo root) |
| Docker build context | `backend` |
| Start command | the image `CMD`: `alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}` |
| Health check path | `/health` |
| Database | Neon Free (external, permanent) for the zero-cost target; Render PostgreSQL is paid and its free tier expires after 30 days |

- **Provisioning (Free Blueprint):** ensure the repo has both `render.yaml` and
  `render.free.yaml`; Render may ask which Blueprint file to use. `render.free.yaml` creates only
  the Free web service and prompts for `DATABASE_URL` (Neon) plus the bootstrap admin values.
- **Provisioning (manual):** create a Docker web service pointing at `backend/Dockerfile` with
  build context `backend`, Free instance type, health check `/health`, and the variables in
  Step 3.
- **Migrations** run automatically on every deploy (the container `CMD`). To run them manually,
  open the service **Shell** and run `alembic upgrade head`.
- **API custom domain:** service → **Settings → Custom Domains** → add
  `api.rimssuppliesandhardware.co.ke`. Render shows the DNS target and issues TLS once DNS
  resolves.

## Step 2 - Frontend on Vercel

| Setting | Value |
| --- | --- |
| Root Directory | `rims-delivery-ui` |
| Framework preset | Vite (auto-detected) |
| Install command | `npm ci` |
| Build command | `npm run build` (= `tsc --noEmit && vite build`) |
| Output directory | `dist` |
| Node version | 22 (`.nvmrc`) |
| Environment variables | none |

Then **Settings → Domains** → add `rimssuppliesandhardware.co.ke` and
`www.rimssuppliesandhardware.co.ke`, and set the apex as the primary domain.

## Step 3 - Backend environment variables

Set these in the Render dashboard (service → Environment). Annotated copy:
`backend/.env.production.example`. Never commit real values.

| Variable | Value | Notes |
| --- | --- | --- |
| `ENVIRONMENT` | `production` | Required for the production guardrails. |
| `DEBUG` | `false` | |
| `DOCS_ENABLED` | `false` | Disables `/docs` and `/openapi.json`. |
| `SESSION_HTTPS_ONLY` | `true` | Required when `ENVIRONMENT=production`. |
| `TRUST_FORWARDED_FOR` | `true` | Real client IPs for rate limiting behind the proxies. |
| `CSRF_PROTECTION` | `true` | |
| `DATABASE_URL` | Neon **direct** connection string (no `-pooler` host) | Production currently uses the direct URL **without a query string** because the deployed commit predates the new normalisation. Once the normalisation in `backend/app/db/urls.py` is committed and deployed, `sslmode` and `channel_binding` are translated automatically. Do not add libpq-only parameters before then. |
| `SESSION_SECRET` | random ≥64 chars | Generate: `python -c "import secrets;print(secrets.token_urlsafe(48))"` |
| `JWT_SECRET` | a different random ≥64 chars | |
| `CORS_ORIGINS` | `https://rims-delivery-ui.vercel.app,https://rimssuppliesandhardware.co.ke,https://www.rimssuppliesandhardware.co.ke` | Safety net; requests are same-origin. The Vercel URL is required for direct cross-origin calls. |
| `GEOCODING_PROVIDER` / `ROUTING_PROVIDER` | `osm` | Keyless public OSM; rate-limited. |
| `PROVIDER_USER_AGENT` | `RIMsDeliveryPricing/1.0 (contact: <your operations email>)` | Required courtesy header; use a real address. |
| `COUNTRY_CODE` | `ke` | |
| `BOOTSTRAP_ADMIN_EMAIL` / `BOOTSTRAP_ADMIN_PASSWORD` | first admin | Used only when no users exist. |
| `REDIS_URL` | optional | Omit for the in-process cache on a single instance. |

## Step 4 - DNS

Do not move the domain's nameservers to Vercel: that transfers **all** records, including mail,
and will break email unless you recreate every MX/TXT record first. Add records at the existing
DNS provider instead.

### Verified requirements (fixed; true regardless of provider)

- The apex `rimssuppliesandhardware.co.ke` must point at Vercel.
- `www` must point at Vercel (or be redirected to the apex).
- The API hostname `api.rimssuppliesandhardware.co.ke` must point at the Render service.
- Existing mail records must be preserved untouched.

### Values you must copy from the dashboards (never invent these)

Open the panels first; each shows the exact records to create. Nothing below is your final value.

| Record | Name | Where the value comes from |
| --- | --- | --- |
| A or CNAME | `@` (apex) | Vercel → Project → **Settings → Domains** (Vercel shows the exact record) |
| CNAME | `www` | Vercel → **Settings → Domains** |
| CNAME | `api` | Render → service → **Settings → Custom Domains** (the `*.onrender.com` target it displays) |

Vercel commonly shows an apex `A` of `76.76.21.21` and `www` `CNAME` to `cname.vercel-dns.com`;
treat those as reference only and confirm against your project's Domains panel. If you do not add
the domains to the dashboards first, you will not know the correct values - do that first.

### Email

This machine's DNS lookup for `rimssuppliesandhardware.co.ke` returned **no NS delegation**
(servfail), so **no mail records could be observed and none can be assumed**. Before any change,
record the domain's current `MX`, `SPF`/`TXT` and any DKIM records at the registrar, and recreate
them verbatim if you ever change providers. Adding the A/CNAME records above at the current
provider does not affect mail.

## Step 5 - Verification checklist (run only after deploying)

```bash
# API host directly
curl -fsS https://api.rimssuppliesandhardware.co.ke/health
curl -fsS https://api.rimssuppliesandhardware.co.ke/ready
# Through the Vercel proxy (same origin the browser uses)
curl -fsS https://rimssuppliesandhardware.co.ke/health
curl -fsS https://rimssuppliesandhardware.co.ke/ready
```

Then in a browser: the site loads over valid HTTPS; `www` redirects to the apex; admin sign-in
succeeds and survives a refresh (proves the first-party cookie); a location in the price list
quotes a fixed price and one outside quotes distance × KES 150 with a whole-shilling total.
Report a step as passing only once you have seen it. Note `/ready` reports
`pricingConfigured: false` until an admin activates a pricing version with rules.

## Updates and rollback

- Frontend: push to `main`; Vercel redeploys.
- Backend: push to `main`; Render redeploys and re-runs migrations on start.
- Rollback: redeploy a previous build from the Vercel/Render dashboards.

## Troubleshooting

- **Login loops back to sign-in**: the request is not same-origin. Confirm the `/api/*` rewrite is
  present and points at the live API host, and that `SESSION_HTTPS_ONLY=true`.
- **5xx on the site but the API host works directly**: the `vercel.json` destination is stale.
- **`/ready` shows `database: error`**: the `DATABASE_URL` is wrong or the database is still
  provisioning.
- **Everyone shares one rate-limit bucket**: set `TRUST_FORWARDED_FOR=true`.
- **Blueprint fails on `dockerfilePath`/`dockerContext`**: they are relative to the repo root -
  keep `./backend/...`.

## Remaining cleanup items

1. Delete Render `rims-postgres` after `2026-11-18T10:05:13Z` (or once the Neon deployment has
   been stable). It is free and no longer serves production traffic; keep it only as a rollback
   copy until then.
2. Keep the Render `DATABASE_URL` query-free until a build containing the URL normalisation is
   live. The service is configured to auto-deploy `main`; documentation/tooling updates do not
   need a manual `render deploys create`.
3. Add a Neon usage alert and keep periodic dumps. Neon Free retains only 6 hours of history.

## Local verification performed (reproducible)

Run from `backend/` unless noted:

```powershell
..\.venv\Scripts\python.exe -m pytest -q                 # full suite
..\.venv\Scripts\python.exe -m mypy app                  # type check
..\.venv\Scripts\python.exe -m ruff check app tests      # linter
# Frontend, from rims-delivery-ui/
npm run typecheck
npm run build
# Migrations + startup against a throwaway PostgreSQL 16
$env:DATABASE_URL="postgresql://rims:check@127.0.0.1:55432/rims"
..\.venv\Scripts\python.exe -m alembic upgrade head
```

Committed and deployed earlier: `rims-delivery-ui/vercel.json`, `rims-delivery-ui/.nvmrc`,
`render.yaml`, `backend/.env.production.example`, and the `$PORT`-aware `backend/Dockerfile`.
This commit adds `render.free.yaml`, `DEPLOYMENT_FREE.md`, the backup/restore/check/verify scripts
in `scripts/`, and the Neon query-string normalisation in `backend/app/db/urls.py` with its tests.
The production database URL remains query-free, so it works with either build. The service
auto-deploys `main`; no manual deployment was triggered for these changes.
