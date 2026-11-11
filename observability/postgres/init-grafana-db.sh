#!/bin/sh
set -eu

until pg_isready -q; do
    sleep 2
done

psql --set=ON_ERROR_STOP=1 --set=grafana_password="$GRAFANA_DB_PASSWORD" <<'SQL'
SELECT format('CREATE ROLE grafana LOGIN PASSWORD %L', :'grafana_password')
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'grafana') \gexec
SELECT format('ALTER ROLE grafana WITH LOGIN PASSWORD %L', :'grafana_password') \gexec
SQL

if [ "$(psql -tAc "SELECT 1 FROM pg_database WHERE datname = 'grafana'")" != "1" ]; then
    createdb --owner=grafana grafana
fi

psql --set=ON_ERROR_STOP=1 -d grafana -c "GRANT ALL ON SCHEMA public TO grafana"
