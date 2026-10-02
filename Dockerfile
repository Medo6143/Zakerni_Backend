# Zakerni backend image. One image, three Railway services:
#   web    (default CMD: migrate + daphne, HTTP and WebSocket)
#   worker (start command: celery -A config worker -l info --concurrency 2)
#   beat   (start command: celery -A config beat -l info)
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DJANGO_SETTINGS_MODULE=config.settings.prod

WORKDIR /app

COPY requirements/ requirements/
RUN pip install -r requirements/prod.txt

COPY . .

# Build-time only values so settings import; real values come from Railway variables.
RUN DJANGO_SECRET_KEY=build-only-not-secret \
    DATABASE_URL=sqlite:////tmp/build.sqlite3 \
    python manage.py compile_po \
 && DJANGO_SECRET_KEY=build-only-not-secret \
    DATABASE_URL=sqlite:////tmp/build.sqlite3 \
    python manage.py collectstatic --noinput \
 && rm -f /tmp/build.sqlite3

RUN useradd --create-home --uid 1000 app && chown -R app:app /app
USER app

EXPOSE 8000
CMD ["sh", "/app/start.sh"]
