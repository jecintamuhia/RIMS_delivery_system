# RIMs Hardware & Supplies delivery pricing

RIMs prices each delivery with one of two explicitly separated models. If the location matches a configured RIMs destination, the quote uses the official fixed price from the active price list (**model A**) — the road distance never changes it. If the location is outside the price list and RIMs has configured an active distance rate, the quote uses the real road distance multiplied by that rate (**model B**). The two models never blend, and the engine never invents a rate, a distance or a nearest-neighbour price. Distance-based amounts are carried to the cent and the final payable is rounded to the nearest whole Kenyan shilling. If routing, destination matching, or active pricing is unavailable, the quote is left unpriced or flagged for manual review and the customer is directed to RIMs for a quotation.

## Architecture

- `backend/`: FastAPI modular monolith, async SQLAlchemy, Alembic migrations, signed httpOnly admin sessions, RBAC, CSRF checks, audit logging, quote pipeline, hybrid pricing engine (fixed destination + distance-based), and provider adapters.
- `rims-delivery-ui/`: React 19, TypeScript, Vite, TanStack Query and Leaflet. Customer and admin pages use the same typed API client; the API is the source of quote amounts and destination data.
- PostgreSQL is the deployment database; SQLite is supported for local development/tests. Redis is optional locally and enabled by the Docker Compose deployment.
- Nominatim and OSRM are the default real, keyless geocoding and road routing providers. Their public endpoints are rate-limited courtesy services. Mapbox adapters are available with a server-side API key.

The configured dispatch pin defaults to **Rims Supplies and Hardware, Kenyatta Ave, Naivasha, Nakuru County, Kenya** at `-0.7256336, 36.4448417`. Admins can update the named point and coordinates under Dispatch & Settings.

## Local development

Requirements: Python 3.12+, Node 22+, npm.

### API

```powershell
cd backend
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e '.[dev,postgres,redis]'
Copy-Item .env.example .env
alembic upgrade head
python -m app.cli.verify_schema
uvicorn app.main:app --reload
```

Set a unique local `SESSION_SECRET` and `JWT_SECRET` in `backend/.env`. To bootstrap the first admin on an empty database, set `BOOTSTRAP_ADMIN_EMAIL` and `BOOTSTRAP_ADMIN_PASSWORD` before the first API start. Bootstrap only creates an account when no users exist. Never use development values or shared demo credentials in production.

Health endpoints are `/health` and `/ready`; API docs are at `/docs` unless `DOCS_ENABLED=false`.

### Frontend

```powershell
cd rims-delivery-ui
npm ci
Copy-Item .env.example .env.local
npm run dev
```

Vite proxies `/api` to `http://localhost:8000`. `VITE_USE_MOCKS=false` is required for a real customer/admin demonstration and is the checked-in default. The optional mock harness is development-only and visibly labels itself; its addresses, quotes and prices are not RIMs data.

## Database and pricing setup

1. Apply schema changes with `alembic upgrade head`; check metadata with `python -m app.cli.verify_schema`.
2. Sign in using the admin account provisioned for this environment.
3. Open **Pricing Versions** and import `backend/data/pricing/rims_transport_costs.csv` into a new draft version.
4. Confirm the imported destinations and fixed amounts against the approved RIMs source sheet. Preserve flagged names for review: `G!TUAMBA`, `TOWN AREA`, `FLYOVER`, `JUNCTION`, `DTI`, `SLAUGHTER`, `DCK`, and `VI`.
5. Validate the draft, record reviewer approval, then activate it. Only an active version is used for new quotes; prior quote records retain the version and amount used.
6. Review the dispatch pin and contact details under **Dispatch & Settings**. Destination coordinates, aliases and catchment data are maintained under **Destinations**.
7. The distance-based fallback (model B) is configured under **Distance Pricing**. It applies only to locations outside the fixed price list, and only while a rate is active. A fresh install seeds a 150 KES/km default rate; change it only on RIMs' instruction. A rate is created as a draft, activated by an admin, and retired to switch it off. Every distance-based quote records the distance, base rate, fuel adjustment, effective rate, calculated amount and rounded payable, so the amount is auditable. The amount the customer pays is the rounded whole-shilling figure.

Do not create road, vehicle, load or percentage pricing adjustments unless RIMs has approved those exact rules. A fixed destination price remains the governing charge wherever a destination matches; the distance rate is only ever a fallback for locations outside the list.

## Docker deployment / client demo

Copy root `.env.example` to `.env`, replace every example password/secret and contact address, then run:

```powershell
docker compose up --build -d
docker compose ps
docker compose logs -f api
```

Compose starts PostGIS, Redis, runs Alembic migrations before the API, bootstraps the first admin only on a clean database, and serves the frontend through Nginx on `http://localhost:8080` by default. It has persistent database/cache volumes. For a locally served demo, the sample `.env` uses `ENVIRONMENT=staging` and non-secure cookies; do not expose that HTTP setup to the internet. For production, set `ENVIRONMENT=production`, `SESSION_HTTPS_ONLY=true`, use strong unique secrets and passwords, and terminate HTTPS at a trusted reverse proxy. Keep `DATABASE_URL`, provider credentials and session secrets server-side.

The public OSM endpoints may decline requests under load. For a committed client demonstration or production traffic, configure supported provider credentials or an organization-managed provider endpoint, provide an honest `PROVIDER_USER_AGENT`, and check `/ready` plus a real quote before the demonstration. A failed route is reported as unavailable; the application never draws a fabricated route or distance.

### Production

For a real deployment with HTTPS, use `docker-compose.prod.yml` and the Caddy TLS edge. Only Caddy publishes ports (80/443); the API and web containers stay on the internal network, the API runs with `ENVIRONMENT=production`, `DOCS_ENABLED=false`, `SESSION_HTTPS_ONLY=true` and `TRUST_FORWARDED_FOR=true`, and certificates are issued and renewed automatically. See [DEPLOYMENT.md](DEPLOYMENT.md) for the full runbook (server setup, DNS, secrets, first admin, verification, updates and backups).

```bash
cp .env.production.example .env.production   # fill in DOMAIN, secrets and admin credentials
docker compose --env-file .env.production -f docker-compose.prod.yml up -d --build
```

To host the frontend on Vercel and the API on a managed host instead of running both in
Compose, use the split-host setup: Vercel serves the SPA and reverse-proxies `/api/*` to the
API (keeping the session cookie first-party), and the API runs from `backend/Dockerfile` with a
managed PostgreSQL database. See [DEPLOYMENT_VERCEL.md](DEPLOYMENT_VERCEL.md); `render.yaml` and
`rims-delivery-ui/vercel.json` hold the host configuration.

## Tests and checks

```powershell
cd backend
python -m pytest
python -m mypy app
python -m ruff check app tests

cd ..\rims-delivery-ui
npm run typecheck
npm run build
```

The API tests exercise authentication/RBAC, pricing/version validation, import validation, destination resolution, routing failures and dispatch settings. To complete a live-provider demonstration, use two customer pins that resolve to the same destination and verify the same fixed fee despite different routed distances.

## Important environment variables

Backend settings are defined and validated in `backend/app/config.py`; use `backend/.env.example` as the local reference. Key settings include `DATABASE_URL`, `REDIS_URL`, `SESSION_SECRET`, `SESSION_HTTPS_ONLY`, `CORS_ORIGINS`, `BOOTSTRAP_ADMIN_EMAIL`, `BOOTSTRAP_ADMIN_PASSWORD`, `GEOCODING_PROVIDER`, `ROUTING_PROVIDER`, `MAPS_API_KEY`, `PROVIDER_USER_AGENT`, and the dispatch coordinates. The web client uses `VITE_API_BASE_URL` and `VITE_USE_MOCKS`; see `rims-delivery-ui/.env.example`.
