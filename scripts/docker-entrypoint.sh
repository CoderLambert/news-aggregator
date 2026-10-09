#!/bin/sh
set -eu

case "${DJANGO_ENV:-development}" in
    production)
        # Production migrations are a separate, locked one-shot Compose service.
        ;;
    development)
        # Preserve the existing local Docker startup behavior.
        python /app/backend/manage.py migrate --noinput
        ;;
    *)
        echo "DJANGO_ENV must be exactly 'development' or 'production'." >&2
        exit 2
        ;;
esac

exec python /app/start_waitress.py
