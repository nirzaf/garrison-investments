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

## Deploy Commands

From the local repo:

```sh
rsync -az --delete \
  --exclude '.git/' \
  --exclude '.env' \
  --exclude 'frontend/node_modules/' \
  --exclude 'frontend/dist/' \
  --exclude 'prototype/node_modules/' \
  --exclude 'backend/.venv/' \
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

## Sample Credentials

Temporary staging login created by `scripts/seed.py`:

- Admin email: `fazrin@quadrate.lk`
- Temporary password: `YahmikAllah@123`

These credentials are for staging smoke tests only. Change or remove them before any production deployment.

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
