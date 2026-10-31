#!/bin/sh
# Container start-up: wait for MySQL, apply the migrations, collect the static
# files and then hand over to gunicorn (or to whatever CMD was given).
set -e

if [ "${DB_ENGINE}" = "mysql" ]; then
  echo "Waiting for MySQL at ${DB_HOST}:${DB_PORT} ..."
  until mysqladmin ping -h"${DB_HOST}" -P"${DB_PORT}" --silent 2>/dev/null; do
    sleep 2
  done
  echo "MySQL is up."
fi

python manage.py migrate --no-input
# No --clear: during a blue-green release both slots share the static volume, and
# clearing it would delete the files the live slot is still serving. The file
# names carry a content hash, so old and new versions live side by side.
python manage.py collectstatic --no-input >/dev/null

if [ "${SEED_DEMO_DATA}" = "1" ]; then
  echo "Seeding demonstration data ..."
  python manage.py seed_demo || true
fi

exec "$@"
