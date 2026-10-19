# Production deployment: Vercel (frontend) + managed API (backend)

This is the runbook for running RIMs Delivery on a custom domain with the Vite frontend on
Vercel and the FastAPI backend on a managed host. It complements [DEPLOYMENT.md](DEPLOYMENT.md),
which covers the self-hosted Docker Compose + Caddy path.

## Why this shape

The admin session cookie is `HttpOnly` + `SameSite=Lax`, and the frontend calls the API with
`credentials: "include"`. Browsers only send a `Lax` cookie on same-site requests, and the app
issues one on `https://rimssuppliesandhardware.co.ke`. Therefore the API must appear on the
**same origin** as the site.

Vercel can host the static Vite build and **reverse-proxy requests to a different origin**. So:

- Vercel serves the SPA **and** proxies `/api/*`, `/health` and `/ready` to the API host.
- The browser only ever talks to `rimssuppliesandhardware.co.ke`, so cookies are first-party
  and no CORS dance is needed.
- The API keeps a persistent database, background tasks and in-process/Redis caching, which a
  pure serverless frontend host cannot provide.

The proxy destination lives in `rims-delivery-ui/vercel.json`. It is hard-coded to
`https://api.rimssuppliesandhardware.co.ke`; change it there if you choose a different API
hostname.

```
browser ─▶ https://rimssuppliesandhardware.co.ke  (Vercel: static SPA)
                 │  /api/* , /health , /ready  →  https://api.rimssuppliesandhardware.co.ke
                 ▼
        FastAPI on Render + managed PostgreSQL
```

## Prerequisites

- A GitHub account with access to this repository (Vercel and Render both deploy from GitHub).
- A Vercel account, a Render account (or any Docker host), and access to the DNS records for
  `rimssuppliesandhardware.co.ke`.
- The repository pushed to GitHub (`main`).

## Step 1 - Deploy the API (Render)

`render.yaml` at the repository root is a Blueprint that creates the web service and a managed
PostgreSQL database. Either use it or create the resources by hand.

### Option A - Blueprint

1. Render dashboard → **New → Blueprint** → connect the GitHub repo.
2. Render reads `render.yaml` and prompts for the `sync: false` secrets
   (`BOOTSTRAP_ADMIN_EMAIL`, `BOOTSTRAP_ADMIN_PASSWORD`). Fill them in (the admin password can be
   blank and created later from the app).
3. Review the plan/region and apply. Render builds `backend/Dockerfile`, runs
   `alembic upgrade head`, then starts Uvicorn on the injected `$PORT`.

### Option B - Manual

1. **New → PostgreSQL**: name `rims-postgres`, database `rims`, user `rims`.
2. **New → Web Service**: connect the repo, set **Root Directory** `backend`,
   **Runtime** Docker, **Health Check Path** `/health`.
3. Add the environment variables from Step 3.

### Add the API custom domain

Render → the `rims-api` service → **Settings → Custom Domains** → add
`api.rimssuppliesandhardware.co.ke`. Render shows the DNS target (a CNAME) - record it for
Step 4. Render provisions the TLS certificate once DNS resolves.

## Step 2 - Deploy the frontend (Vercel)

1. Vercel → **Add New → Project** → import this repository.
2. Set **Root Directory** to `rims-delivery-ui`. Vercel detects Vite via `vercel.json`
   (`buildCommand: npm run build`, `outputDirectory: dist`, `installCommand: npm ci`).
3. No build-time secrets are required. The app defaults to the same-origin API base
   (`/api/v1`); do not set `VITE_API_BASE_URL` unless you deliberately point at a different API.
4. Deploy. Then **Settings → Domains** → add `rimssuppliesandhardware.co.ke` and
   `www.rimssuppliesandhardware.co.ke`. Set the apex as the primary domain so `www` redirects
   to it.

## Step 3 - Environment variables

Set these on the API host (Render dashboard → service → Environment). Full annotated list:
`backend/.env.production.example`. Never commit real values.

| Variable | Value | Notes |
| --- | --- | --- |
| `ENVIRONMENT` | `production` | Enables the production guardrails. |
| `DEBUG` | `false` | |
| `DOCS_ENABLED` | `false` | Disables `/docs` and `/openapi.json`. |
| `SESSION_HTTPS_ONLY` | `true` | Required when `ENVIRONMENT=production`; forces Secure cookies. |
| `TRUST_FORWARDED_FOR` | `true` | Trust the platform proxy for real client IPs (rate limiting). |
| `CSRF_PROTECTION` | `true` | |
| `DATABASE_URL` | Render Internal Connection String | `postgresql://…` is upgraded to asyncpg automatically. |
| `SESSION_SECRET` | random 64+ chars | `python -c "import secrets;print(secrets.token_urlsafe(48))"` |
| `JWT_SECRET` | a different random 64+ chars | |
| `CORS_ORIGINS` | `https://rimssuppliesandhardware.co.ke,https://www.rimssuppliesandhardware.co.ke` | Safety net only. |
| `GEOCODING_PROVIDER` / `ROUTING_PROVIDER` | `osm` | Keyless OSM, rate-limited. |
| `PROVIDER_USER_AGENT` | `RIMsDeliveryPricing/1.0 (contact: …)` | Use a real operations email. |
| `COUNTRY_CODE` | `ke` | |
| `BOOTSTRAP_ADMIN_EMAIL` / `BOOTSTRAP_ADMIN_PASSWORD` | first admin | Only used when no users exist. |
| `REDIS_URL` | optional | Omit for the in-process cache on a single instance. |

The frontend needs **no** secrets. Public Vite variables are bundled into the client and are
never a place for credentials.

## Step 4 - DNS records

Keep the domain's existing nameservers and add records at the current DNS provider. **Do not
move the nameservers to Vercel** unless you also intend to move email and every other record -
that would drop any existing MX/DKIM/SPF records and break mail.

Get the exact values from the Vercel and Render dashboards after adding the domains; they are
shown there. Typical records:

| Type | Name | Value | Purpose |
| --- | --- | --- | --- |
| `A` | `@` (apex) | `76.76.21.21` | Vercel site |
| `CNAME` | `www` | `cname.vercel-dns.com` | Vercel site (redirects to apex) |
| `CNAME` | `api` | `<service>.onrender.com` | API host |

Leave existing `MX`/`TXT` (email) records untouched. Propagation is usually minutes, up to a few
hours for `.co.ke`.

## Step 5 - Verify (only claim what you actually observe)

Replace the domain if it differs.

```bash
curl -fsS https://rimssuppliesandhardware.co.ke/health         # proxied API liveness
curl -fsS https://rimssuppliesandhardware.co.ke/ready          # database + cache + pricing
curl -fsS https://api.rimssuppliesandhardware.co.ke/health     # API host directly
```

Then, in a browser:

1. The site loads over HTTPS with a valid certificate; `www` redirects to the apex.
2. Admin sign-in at the admin route succeeds and the session survives a refresh (proves the
   cookie is accepted as first-party).
3. A location inside the price list quotes the fixed price; a location outside it quotes
   distance × KES 150; the payable total is a whole number and the explanation reconciles the
   rounding.

Only report a step as working once you have seen it.

## Updates

- Frontend: push to `main`; Vercel redeploys automatically.
- Backend: push to `main`; Render redeploys; the container runs `alembic upgrade head` on start.

## Troubleshooting

- **Admin login loops back to the login page**: the request is not same-origin. Confirm the
  Vercel `/api/*` rewrite is present and points at the live API host, and that `SESSION_HTTPS_ONLY=true`.
- **`/ready` fails on a fresh deploy**: migrations or the pricing seed have not finished, or the
  database URL is wrong. Check the service logs.
- **5xx from `/api/*` on the site but the API host works directly**: the `vercel.json` rewrite
  destination is stale or the wrong hostname.
- **Rate limiting shows one client IP for everyone**: set `TRUST_FORWARDED_FOR=true`.

## What cannot be automated from the repository

Creating the Vercel/Render resources, provisioning the database, and editing DNS all require
account access. Those steps are manual by design. The repo supplies everything else:
`rims-delivery-ui/vercel.json`, `rims-delivery-ui/.nvmrc`, `render.yaml`,
`backend/.env.production.example`, and the `$PORT`-aware `backend/Dockerfile`.
