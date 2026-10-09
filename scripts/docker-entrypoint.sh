#!/bin/sh
set -eu

# Migrations are idempotent and keep a newly cloned or upgraded database in
# sync before Waitress starts accepting requests.
python /app/backend/manage.py migrate --noinput

exec python /app/start_waitress.py
