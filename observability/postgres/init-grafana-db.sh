#!/bin/sh
set -eu

until pg_isready -q; do
    sleep 2
done

if [ "$(psql -tAc "SELECT 1 FROM pg_roles WHERE rolname = 'grafana'")" != "1" ]; then
    psql -v password="$GRAFANA_DB_PASSWORD" \
        -c "CREATE ROLE grafana LOGIN PASSWORD :'password'"
else
    psql -v password="$GRAFANA_DB_PASSWORD" \
        -c "ALTER ROLE grafana WITH LOGIN PASSWORD :'password'"
fi

if [ "$(psql -tAc "SELECT 1 FROM pg_database WHERE datname = 'grafana'")" != "1" ]; then
    createdb --owner=grafana grafana
fi

psql -d grafana -c "GRANT ALL ON SCHEMA public TO grafana"
