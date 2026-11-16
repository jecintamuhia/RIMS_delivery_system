# Permanent zero-cost deployment (Render Free + Neon Free)

This is the live KES 0/month architecture for the RIMs Delivery API. The frontend stays on Vercel
and reaches the API through the same-origin proxy in `rims-delivery-ui/vercel.json`.

## Final architecture (verified 2026-11-16)

```
browser -> Vercel Hobby (SPA + /api proxy) -> Render Free web service -> Neon Free PostgreSQL
```

| Component | Live resource | Free-tier notes |
| --- | --- | --- |
| Frontend | `rims-delivery-ui.vercel.app`, custom domain `rimssuppliesandhardware.co.ke` | Vercel Hobby, unchanged |
| API | Render `rims-api`, Frankfurt, Docker | Free plan, 512 MB / 0.1 CPU, sleeps after 15 idle minutes |
| Database | Neon project `my-first-project`, region `aws-sa-east-1` (São Paulo), PostgreSQL 18.7, database `neondb` | Free plan, 1 GB storage, 100 CU-hours/month, scales to zero after 5 minutes |
| Old database | Render `rims-postgres`, free | Expires `2026-11-18T10:05:13Z`; kept untouched as a rollback copy |

The Render web service and the old Render database are both on the **Free** plan. No paid service,
subscription or trial was activated.

## What was verified against production

| Check | Result |
| --- | --- |
| `GET https://api.rimssuppliesandhardware.co.ke/health` | `status: ok`, environment `production` |
| `GET .../ready` | `ready: true`, database/cache/pricing all `ok` |
| Active fixed price list | `RIMs Transport Costs`, 78 destinations |
| Public config | `RIMs Hardware & Supplies Co. Ltd.` |
| Fixed quote (Olkaria) | `completed`, `fixed_destination`, KES 5500 |
| Distance quote (Nairobi) | `completed`, `distance_based`, 91.17 km x KES 150 = KES 13676 |
| Vercel proxy | `/ready` and `/api/v1/public/*` work on `rims-delivery-ui.vercel.app` |
| CORS preflight | HTTP 200, `Access-Control-Allow-Origin: https://rims-delivery-ui.vercel.app`, credentials `true` |
| CORS GET/POST | Both return the same allowed origin and credentials headers |
| Database cutover | A new live quote was found in Neon and absent from the old Render database |
| Restart persistence | The quote survived a Render service restart and is still readable through the API |
| Admin authentication | Login returned 200 with an `HttpOnly` + `Secure` session cookie; `POST /auth/me` returned `role=admin`, `active=true`, and a CSRF header (credentials were read from the Render environment in memory and never printed) |
| Schema | 16 tables, 61 indexes, 21 foreign keys, 10 check constraints, 4 unique constraints - identical on both databases |
| Data | Per-table content hashes for all 16 tables matched exactly between Render and Neon |
| Migration history | `alembic_head = e4a1d7c9b3f2 (head)` on Neon |

Re-run the live checks any time with:

```powershell
.\scripts\verify-api.ps1
```

## Backup and restore

The cutover backup was created with the Docker-based script and inspected with `pg_restore --list`
(115 TOC entries, all 16 tables and their data). A second copy was placed outside the repository.
The dump is in `backups\` (gitignored) and is not committed.

```powershell
# Dump an external database; you are prompted for the URL without it being echoed.
.\scripts\backup-postgres.ps1

# Inspect row counts, active pricing versions and Alembic head.
.\scripts\check-db.ps1

# Restore into an EMPTY database. The script refuses to pass --clean.
.\scripts\restore-postgres.ps1 -DatabaseUrl "<target-url>" -BackupFile ".\backups\rims-....dump"
```

The scripts run `pg_dump` / `pg_restore` / `psql` through `postgres:17` in Docker, so no local
PostgreSQL client is required. The URL is passed as an environment variable, not on the command
line. For a database on the same Windows host, use `host.docker.internal` instead of `127.0.0.1`.

To verify a restore:

1. Compare the counts with `check-db.ps1` on both databases.
2. Compare table content hashes (see the SQL used during the cutover).
3. Confirm `alembic_head` and both active pricing versions.
4. Only then point the application at the new database.

## Render configuration

The existing service was updated in place; no duplicate service was created. Existing identity,
custom domain, TLS, health check and secrets were preserved.

| Setting | Value |
| --- | --- |
| Service | `rims-api` |
| Repository / branch | `jecintamuhia/RIMS_delivery_system`, `main` |
| Root directory | `backend` |
| Runtime | Docker, `./Dockerfile` relative to the root directory |
| Health check | `/health` |
| Instance type | Free |
| Auto-deploy | On commit to `main` |
| Region | Frankfurt |
| Custom domain | `api.rimssuppliesandhardware.co.ke` |

Environment variables (values are never committed): `ENVIRONMENT`, `DEBUG`, `DOCS_ENABLED`,
`SESSION_HTTPS_ONLY`, `TRUST_FORWARDED_FOR`, `CSRF_PROTECTION`, `COUNTRY_CODE`,
`GEOCODING_PROVIDER`, `ROUTING_PROVIDER`, `PROVIDER_USER_AGENT`, `CORS_ORIGINS`, `DATABASE_URL`,
`SESSION_SECRET`, `JWT_SECRET`, `BOOTSTRAP_ADMIN_EMAIL`, `BOOTSTRAP_ADMIN_PASSWORD`, `PORT`,
`DEFAULT_DISTANCE_RATE_PER_KM`, `AUTO_SEED_DISTANCE_PRICING`.

`CORS_ORIGINS` is exactly:

```text
https://rims-delivery-ui.vercel.app,https://rimssuppliesandhardware.co.ke,https://www.rimssuppliesandhardware.co.ke
```

No wildcard is used and credentials are allowed.

### Neon URL compatibility note

The live `DATABASE_URL` uses the Neon direct endpoint **without a query string**. That works both
before and after the URL-normalisation change in this commit: asyncpg's default TLS negotiation
connects to Neon successfully.

The normalisation translates `sslmode` to asyncpg's `ssl` and drops `channel_binding` /
`pgbouncer`. Once a build containing it is live, the full Neon URL
(`?sslmode=require&channel_binding=require`) is supported as-is. Keeping the query-free URL is
also fine and avoids depending on the new code path.

## Free-tier limitations and operational risks

- **Render cold start:** after 15 idle minutes the service sleeps; the first request can take
  30-60 seconds. Neon also wakes on the first query. A loading/retry state is required for the
  first request of the day.
- **Render instance hours:** 750 hours/month. A single always-on free service uses about 720
  hours, leaving little headroom; a second free service would exceed the allowance.
- **Neon region:** the project is in `aws-sa-east-1` (São Paulo), while Render runs in Frankfurt.
  Queries work but have higher latency than a co-located database. Moving the Neon project to
  `aws-eu-central-1` would be a future improvement, not a correctness issue.
- **Neon storage/compute:** 1 GB storage and 100 CU-hours/month. Exceeding the compute quota
  suspends the project until the monthly reset; set a usage alert in the Neon console.
- **Neon restore window:** the free project's history retention is 6 hours (point-in-time). Keep
  regular `backup-postgres.ps1` dumps; do not rely on Neon history for long-term recovery.
- **No persistent disk on Render Free:** the app does not write files, so this is fine. Do not add
  file uploads without object storage.
- **In-process background work:** quote processing runs in the API process. A restart can
  interrupt an in-flight quote; clients should retry. This was already the behavior before the
  cutover.
- **Single instance:** the memory cache and rate limiter are per process. This is acceptable at the
  current traffic level.

## Recovery procedure

### Roll back the application to the old Render database

The old database is still available until its expiry on `2026-11-18T10:05:13Z`.

1. Render -> `rims-api` -> Environment -> set `DATABASE_URL` to the Render **internal**
   connection string (the old value).
2. Trigger a deploy.
3. Run `.\scripts\verify-api.ps1`.

### Restore from the backup

1. Create a new Neon branch/database (or another empty PostgreSQL database).
2. Run `.\scripts\restore-postgres.ps1` with the empty target and the latest dump.
3. Verify with `.\scripts\check-db.ps1` and the content-hash comparison.
4. Point `DATABASE_URL` at the restored database and deploy.

Never restore with `--clean` into a live database; the provided script does not pass it.

## Current cleanup items

1. Delete the old Render `rims-postgres` after the new deployment has been stable. It is free, so
   there is no bill, but it expires on its own on 2026-11-18. Do not delete it until you are
   satisfied with the Neon deployment and have an off-machine copy of the dump.
2. Keep the Render `DATABASE_URL` query-free until a build containing the URL normalisation is
   live; after that the full Neon URL is also supported.
3. Add a Neon usage alert and keep periodic dumps; the free plan has no long-term automated
   backup.
