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
    # Bootstrap the first admin from DJANGO_SUPERUSER_* (no-op when it already exists).
    if [ -n "$DJANGO_SUPERUSER_USERNAME" ] && [ -n "$DJANGO_SUPERUSER_PASSWORD" ]; then
      python manage.py createsuperuser --noinput --moodle_username "$DJANGO_SUPERUSER_USERNAME" 2>/dev/null || true
    fi
    exec daphne -b 0.0.0.0 -p "${PORT:-8000}" config.asgi:application
    ;;
esac
