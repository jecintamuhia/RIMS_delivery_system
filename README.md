# RIMs Hardware & Supplies delivery pricing

RIMs is a fixed destination delivery pricing system. The customer selects a real location, the API resolves it, obtains a road route and distance, resolves a configured destination, and prices it from the active RIMs price list. Distance is informational and does not set the fee. If routing, destination matching, or active pricing is unavailable, the quote remains unpriced and the customer is directed to RIMs for a manual quote.

## Architecture

- `backend/`: FastAPI modular monolith, async SQLAlchemy, Alembic migrations, signed httpOnly admin sessions, RBAC, CSRF checks, audit logging, quote pipeline, fixed pricing engine, and provider adapters.
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

Do not create distance, fuel, road, vehicle, load, or percentage pricing adjustments unless RIMs has approved those exact rules. Imported fixed destination prices must remain the governing base charge.

## Docker deployment / client demo

Copy root `.env.example` to `.env`, replace every example password/secret and contact address, then run:

```powershell
docker compose up --build -d
docker compose ps
docker compose logs -f api
```

Compose starts PostGIS, Redis, runs Alembic migrations before the API, bootstraps the first admin only on a clean database, and serves the frontend through Nginx on `http://localhost:8080` by default. It has persistent database/cache volumes. For a locally served demo, the sample `.env` uses `ENVIRONMENT=staging` and non-secure cookies; do not expose that HTTP setup to the internet. For production, set `ENVIRONMENT=production`, `SESSION_HTTPS_ONLY=true`, use strong unique secrets and passwords, and terminate HTTPS at a trusted reverse proxy. Keep `DATABASE_URL`, provider credentials and session secrets server-side.

The public OSM endpoints may decline requests under load. For a committed client demonstration or production traffic, configure supported provider credentials or an organization-managed provider endpoint, provide an honest `PROVIDER_USER_AGENT`, and check `/ready` plus a real quote before the demonstration. A failed route is reported as unavailable; the application never draws a fabricated route or distance.

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
