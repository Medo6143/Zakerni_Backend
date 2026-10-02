#!/bin/sh
# One image, three Railway services: the role comes from SERVICE_ROLE, else the Railway service name.
set -e
role="${SERVICE_ROLE:-${RAILWAY_SERVICE_NAME:-web}}"

case "$role" in
  worker)
    exec celery -A config worker -l info --concurrency "${CELERY_CONCURRENCY:-2}"
    ;;
  beat)
    exec celery -A config beat -l info --schedule /tmp/celerybeat-schedule
    ;;
  *)
    python manage.py migrate --noinput
    exec daphne -b 0.0.0.0 -p "${PORT:-8000}" config.asgi:application
    ;;
esac
