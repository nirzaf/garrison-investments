# Staging Deployment

## Environment

- Public URLs: `https://garrisonstg.seasonenterprise.com` and `https://www.garrisonstg.seasonenterprise.com`
- VPS: Contabo `207.180.209.123`
- SSH: `ssh -i /Users/qts/.ssh/id_ed25519 root@207.180.209.123`
- Remote path: `/opt/garrison-investments-staging`
- Docker Compose project: `garrisonstg`
- Public routing: Cloudflare proxied DNS for `garrisonstg.seasonenterprise.com` points to `207.180.209.123`; `www.garrisonstg.seasonenterprise.com` is DNS-only because the nested `www` host uses the origin Let's Encrypt certificate. VPS Nginx proxies both hosts to `127.0.0.1:3310`.
- Cloudflare account: `Aathiffurkhan2002@gmail.com's Account` (`cf5b16793437d616449941f874eca77f`), zone `seasonenterprise.com` (`6378d9b2f78911ea2fe731e6b74247c1`), nameservers `quinton.ns.cloudflare.com` and `sara.ns.cloudflare.com`. Do not store Cloudflare API tokens in this document.
- Host isolation: only `garrisonstg.seasonenterprise.com` and `www.garrisonstg.seasonenterprise.com` may proxy to the Garrisons staging stack. Root domains such as `seasonenterprise.com` and `www.seasonenterprise.com` must continue serving the existing Season Enterprises page.
- Existing deployments are isolated and must not be restarted: `/opt/ginreactaccounts`, `/opt/season-enterprises`, and their containers.

## Runtime Layout

Staging uses its own Compose file and private Docker resources:

- Compose file: `/opt/garrison-investments-staging/docker-compose.staging.yml`
- Environment file: `/opt/garrison-investments-staging/.env.staging`
- Frontend entrypoint: `127.0.0.1:3310`
- Internal backend: `backend:8000`
- Volumes:
  - `garrisonstg-pgdata`
  - `garrisonstg-redisdata`
  - `garrisonstg-miniodata`

The staging SMTP settings are stored only in the VPS `.env.staging` file. They use Office365 SMTP through `smtp.office365.com:587`, TLS enabled, and the sender identity `Quadrate Mail Service <mail@quadrate.lk>`. Do not commit SMTP passwords or Contabo/API secrets to this repository.

Add `FRONTEND_BASE_URL=https://garrisonstg.seasonenterprise.com` to `/opt/garrison-investments-staging/.env.staging` so outgoing approval notification emails contain the correct absolute portal URLs.

For UAT speed, staging can accept a shared login OTP by setting `APP_ENV=staging` and `STAGING_LOGIN_OTP=<six-digit-code>` in `/opt/garrison-investments-staging/.env.staging`. This shortcut applies only to login OTP verification and is ignored outside `APP_ENV=staging`.

## Deploy Commands

From the local repo:

```sh
rsync -az --delete \
  --exclude '.git/' \
  --exclude '.env' \
  --exclude '.env.staging' \
  --exclude '.env.prod' \
  --exclude 'frontend/node_modules/' \
  --exclude 'frontend/dist/' \
  --exclude 'prototype/node_modules/' \
  --exclude 'backend/.venv/' \
  --exclude 'backend/secrets/' \
  --exclude '.pytest_cache/' \
  --exclude '.ruff_cache/' \
  --exclude '.DS_Store' \
  -e 'ssh -i /Users/qts/.ssh/id_ed25519' \
  /Users/qts/Repos/garrison-investments/ \
  root@207.180.209.123:/opt/garrison-investments-staging/
```

On the VPS:

```sh
cd /opt/garrison-investments-staging
docker compose -p garrisonstg --env-file .env.staging -f docker-compose.staging.yml config --quiet
docker compose -p garrisonstg --env-file .env.staging -f docker-compose.staging.yml up -d --build
docker compose -p garrisonstg --env-file .env.staging -f docker-compose.staging.yml exec -T backend alembic upgrade head
docker compose -p garrisonstg --env-file .env.staging -f docker-compose.staging.yml exec -T backend python scripts/seed.py
```

## Staging Test Credentials

Shared staging login verification OTP:

- OTP: `123456`

Role-specific staging users:

| Role | Email |
| --- | --- |
| Admin | `admin.test@garrisons.lk` |
| General Manager | `gm.test@garrisons.lk` |
| Operation Manager | `operations.test@garrisons.lk` |
| Project Manager | `pm.test@garrisons.lk` |
| Civil Engineer | `engineer.test@garrisons.lk` |
| Civil Supervisor | `supervisor.test@garrisons.lk` |
| Store Keeper | `storekeeper.test@garrisons.lk` |
| Accounts | `accounts.test@garrisons.lk` |

Staging password:

- Set `SEED_DEFAULT_PASSWORD` in `/opt/garrison-investments-staging/.env.staging` before running `python scripts/seed.py`.

### What Each Test User Can Do

| Role | Key Permissions | Primary Features & Responsibilities |
| --- | --- | --- |
| **Admin** | All 16 permissions (full system access) | Full CRUD on users/projects/reports/inventory/suppliers/documents/finance; audit logs; security screens; can override submitted reports; company-wide analytics and delivery planning |
| **General Manager** | `users:read`, `projects:read`/`:manage`, `dashboard:company`, `reports:view`/`:approve`, `inventory:view`, `suppliers:manage`, `documents:view`/`:manage`, `financial:view` | Executive oversight; cross-project approvals for any report; company-wide dashboard; manage suppliers and documents; view all financial data |
| **Operation Manager** | Same as General Manager (10 permissions) | High-value approvals and escalations; overall operational oversight; receives material request escalations and invoice due notifications; view users but cannot manage them |
| **Project Manager** | `dashboard:scoped`, `projects:read`, `reports:view`/`:approve`, `inventory:view`, `documents:view`/`:manage`, `financial:view` | Scoped to assigned projects only; approve reports/project budgets for their projects; manage documents; view inventory and financials; receives report escalation notifications |
| **Civil Engineer** | `dashboard:scoped`, `projects:read`, `reports:view`/`:submit`, `inventory:view`, `documents:view`/`:manage` | Submit daily reports and material requests; scoped to assigned projects; can only see own reports; manage documents; view inventory |
| **Civil Supervisor** | `dashboard:scoped`, `projects:read`, `reports:view`/`:submit` | Submit supervisor updates and daily reports; scoped to assigned projects; most limited read-only role; Reports nav auto-routes to supervisor update form |
| **Store Keeper** | `dashboard:scoped`, `inventory:view`/`:manage`, `suppliers:manage` | Full inventory management; manage supplier records; handle material requests and stock movements; scoped dashboard; receives material request escalations |
| **Accounts** | `dashboard:scoped`, `projects:read`, `reports:view`, `documents:view`/`:manage`, `financial:view` | Finance features (invoices, payments, bank withdrawals, ledgers); unrestricted project visibility (can view all projects); manage documents; receives invoice due notifications |

> **Note:** Besides the 8 system roles, users are also assigned **project-level roles** (free-form strings like "Project Manager", "Civil Engineer", "Store Keeper") via the `project_members` table. Project-level role assignment controls membership access for scoped roles — a Project Manager can only approve reports in projects they're a member of, while Admin/General Manager/Operation Manager bypass membership checks entirely.

These credentials are for staging smoke tests only. Change or remove them before any production deployment.
Use the configured staging shared OTP for login verification when `STAGING_LOGIN_OTP` is set.

## Verification

```sh
curl -fsS http://127.0.0.1:3310/health
curl -I http://127.0.0.1:3310/
curl -I https://garrisonstg.seasonenterprise.com/
curl -fsS https://garrisonstg.seasonenterprise.com/health
docker ps --filter 'name=garrisonstg' --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'
```

After any Nginx routing edit:

```sh
nginx -t
systemctl reload nginx
```

Control checks for existing deployments:

```sh
curl -sS https://seasonenterprise.com/login | grep -E 'Season|Coming'
curl -sS https://www.seasonenterprise.com/login | grep -E 'Season|Coming'
curl -I https://accounts.seasonenterprise.com/
curl -I https://ledgr.seasonenterprise.com/
docker ps --format 'table {{.Names}}\t{{.Ports}}\t{{.Status}}'
```

## Current Deployment Notes

- Staging was deployed as a separate stack under `garrisonstg`.
- Backend migrations were applied through Alembic.
- Seed data was loaded successfully.
- Local VPS checks passed for `http://127.0.0.1:3310/` and `http://127.0.0.1:3310/health`.
- Cloudflare authoritative DNS returns proxied A/AAAA records for `garrisonstg.seasonenterprise.com`; normal recursive DNS may take a few minutes to catch up.
- The staging certificate is issued through Certbot/Cloudflare DNS validation under the existing `seasonenterprise.com` certificate and includes `www.garrisonstg.seasonenterprise.com`.
- Existing `accounts.seasonenterprise.com` and `ledgr.seasonenterprise.com` checks returned HTTP 200 after the staging Nginx route was added.
- `seasonenterprise.com` and `www.seasonenterprise.com` were explicitly mapped to the existing Season Enterprises coming-soon page so the staging app cannot appear on the root or `www` host.
- `ckc-solution.com` was removed from active VPS Nginx routing, and the old `cloudflared` tunnel service/config was disabled because it only routed that domain.
