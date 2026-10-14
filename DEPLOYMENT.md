# Production deployment

This is the runbook for running RIMs on a real server with HTTPS. The stack is
`docker-compose.prod.yml`: PostGIS, Redis, the API, the web app, and Caddy as the TLS edge.
Only Caddy publishes ports (80 and 443); the API and web containers are reachable only on the
internal network.

## What you need

- A Linux server (Ubuntu 22.04/24.04 LTS or equivalent) with a public IP, 2 vCPU and 4 GB RAM
  minimum, and ports **80** and **443** open in the firewall.
- A domain or subdomain (for example `deliveries.rims.example`) whose **A record points at the
  server's IP**. Caddy cannot issue a certificate until DNS resolves.
- Docker Engine with the Compose plugin.
- The repository on the server (via `git clone`).

## 1. Install Docker (once)

```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker "$USER"   # log out and back in so the group applies
docker version && docker compose version
```

## 2. Point DNS at the server

Create an `A` record for your domain pointing at the server's public IP, and wait for it to
resolve (`dig +short deliveries.rims.example`). Caddy issues the certificate on first start.

## 3. Get the code and secrets

```bash
git clone git@github.com:jecintamuhia/RIMS_delivery_system.git
cd RIMS_delivery_system
cp .env.production.example .env.production
```

Edit `.env.production` and fill in every value. Generate the three secrets with:

```bash
openssl rand -hex 32   # run once each for POSTGRES_PASSWORD, SESSION_SECRET, JWT_SECRET
```

Set `DOMAIN` to your hostname, `ACME_EMAIL` to a real contact, and give
`BOOTSTRAP_ADMIN_PASSWORD` a strong unique value. `.env.production` is gitignored — never commit
it.

## 4. Start the stack

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml up -d --build
docker compose --env-file .env.production -f docker-compose.prod.yml ps
```

On first start the API runs `alembic upgrade head`, then the bootstrap creates the first admin
(only when the database is empty) and seeds the RIMs dispatch point and the default distance
rate. Watch it come up:

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml logs -f api
```

## 5. Verify

```bash
curl -fsS https://deliveries.rims.example/health
curl -fsS https://deliveries.rims.example/ready
```

`/ready` must report `"ready": true`, a `database`/`cache`/`pricing` check of `ok`, and the
active pricing version. Then open the site in a browser and:

1. Sign in at `/admin` with the bootstrap admin, and change the password.
2. Import the price list (**Pricing Versions** → import
   `backend/data/pricing/rims_transport_costs.csv`), then activate it.
3. Request a quote for a listed destination and confirm the fixed RIMs price, then for an unlisted
   location and confirm the distance-based amount.

Because `ENVIRONMENT=production` and `SESSION_HTTPS_ONLY=true`, the admin session cookie is
`Secure`; the admin pages only work over HTTPS. That is the intended production behaviour.

## Updating

```bash
git pull
docker compose --env-file .env.production -f docker-compose.prod.yml up -d --build
```

The database and cache live in named volumes (`postgres_data`, `redis_data`) and survive rebuilds.
Caddy stores certificates in `caddy_data`.

## Backups

Back up the database on a schedule:

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml exec -T db \
  pg_dump -U rims rims | gzip > "rims-$(date +%F-%H%M).sql.gz"
```

Store the dump off the server. Restore with `gunzip -c dump.sql.gz | docker compose ... exec -T db psql -U rims rims`.

## Operations

- Logs: `docker compose --env-file .env.production -f docker-compose.prod.yml logs -f`
- Restart: `docker compose --env-file .env.production -f docker-compose.prod.yml restart`
- Stop (keeps data): `docker compose --env-file .env.production -f docker-compose.prod.yml down`
- Never run `down -v` in production: it deletes the volumes, including the database.

## Notes and limits

- The public Nominatim/OSRM endpoints are courtesy services and may rate-limit production traffic.
  For committed traffic, set an organization-managed `PROVIDER_BASE_URL` or a `MAPS_API_KEY` (add
  them to `.env.production`; the API service reads that file), and make sure
  `PROVIDER_USER_AGENT` names the deployment and a contact.
- Rate limiting is per API instance and in-process. This stack runs a single API container, which
  is correct here. Running multiple API replicas would need a shared limiter.
- Local demo (no HTTPS) still uses the plain `docker-compose.yml`; do not expose it to the
  internet.
