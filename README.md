# Zakerni backend

Django 5 + DRF + Celery. See `../CLAUDE.md` and `../docs/02-backend-architecture.md`
for the rules and layering this code follows.

## Setup

```bash
cd backend
python -m venv .venv
source .venv/Scripts/activate   # Windows Git Bash; use .venv/bin/activate on macOS/Linux
pip install -r requirements/dev.txt

cp ../.env.example ../.env   # docker compose reads the repo-root .env
cp ../.env .env              # Django settings read backend/.env; set TOKEN_ENCRYPTION_KEY
# generate a Fernet key:
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

# infra (from repo root)
docker compose up -d

python manage.py migrate
python manage.py compile_po        # builds locale/*/django.mo (no GNU gettext needed)
python manage.py createsuperuser
python manage.py runserver        # ASGI via daphne: HTTP + the report-chat WebSocket
```

`daphne` is first in `INSTALLED_APPS`, so `runserver` serves `config.asgi` (HTTP and
`ws/v1/reports/<id>/`). The channel layer is Redis (`REDIS_URL`); tests use the in-memory
layer. Production runs an ASGI server instead of gunicorn/WSGI:
`daphne -b 0.0.0.0 -p 8000 config.asgi:application` (or
`uvicorn config.asgi:application --host 0.0.0.0 --port 8000`). The proxy must forward
WebSocket upgrades for `/ws/`. Contract: docs/05-api-spec.md, "Real-time report chat".

Celery (needs Redis from `docker compose up -d`):

```bash
celery -A config worker -l info
celery -A config beat -l info
```

Phone-side fetch: accounts without a stored Moodle token (or SIS password) are skipped by the periodic syncs; their data arrives through `POST /me/lms/ingest` and `POST /me/sis/ingest` after the student connects the university from Settings (`POST /me/lms/connect`). The app has its own accounts (`/auth/register`, `/auth/signin`, `/auth/change-password`); there is no forgot-password flow, so staff use the user admin (password form or the action "Set a temporary password").

Beat schedule (`config/settings/base.py`):

| Task | Schedule |
|---|---|
| `moodle.enqueue_moodle_syncs` | every `MOODLE_SYNC_INTERVAL_MINUTES` (30), jittered per account |
| `reminders.dispatch_due_reminders` | every minute |
| `schedule.expand_lecture_schedules` | daily 00:10 Cairo |
| `reminders.cleanup` / `notifications.cleanup_link_tokens` | daily 03:00 / 03:05 Cairo |

External services: set `FIREBASE_CREDENTIALS_FILE` (service-account JSON path) or `FIREBASE_CREDENTIALS_JSON` (the JSON itself) for push and
`TELEGRAM_BOT_TOKEN` + `TELEGRAM_WEBHOOK_SECRET` for Telegram, then point the bot
webhook at `https://<host>/api/v1/telegram/webhook` with the same `secret_token`.
Without credentials the clients return failed deliveries instead of raising.
Locally there is no public HTTPS URL for the webhook, so run `python manage.py telegram_poll`
instead: it removes any webhook and feeds `getUpdates` to the same handler.

## Settings

Split by environment under `config/settings/`:

- `base.py` — shared settings, reads everything from env via `django-environ`
  (all variables are listed in `../.env.example`).
- `dev.py` — local development (`DJANGO_SETTINGS_MODULE=config.settings.dev`, the default in `manage.py`).
- `test.py` — used by `pytest` (sqlite in-memory, Celery eager, fixed test keys).
- `prod.py` — Railway/PaaS production: required secret key, hosts + CSRF origins (Railway domain added automatically), proxy SSL header, secure cookies, HSTS, WhiteNoise static files, stdout logging, explicit CORS allow-list.

## Deploy on Railway

One image (`Dockerfile`, Python 3.12, non-root, static files collected at build) runs as
three services. Nothing secret is in the image: everything comes from Railway variables.

1. Create a Railway project from this GitHub repo.
2. Add the **PostgreSQL** and **Redis** plugins.
3. Create three services from the same repo, each with **Root Directory** `backend`:

   | Service name | What `start.sh` runs | Public domain |
   |---|---|---|
   | `web` | `migrate` then `daphne -b 0.0.0.0 -p $PORT config.asgi:application` | yes (Generate Domain) |
   | `worker` | `celery -A config worker -l info --concurrency 2` | no |
   | `beat` | `celery -A config beat -l info` (one replica only) | no |

   The image CMD is `start.sh`, which picks the role from `SERVICE_ROLE` or else the
   Railway service name, so the three services need no per-service start command.
   `railway.json` sets the Dockerfile builder and restart on failure (no healthcheck,
   because it applies to every service and only `web` serves HTTP).
   Migrations run only in `web`.
4. Set the variables below on all three services (shared variables or references such as
   `${{Postgres.DATABASE_URL}}` and `${{Redis.REDIS_URL}}`).
5. After the first successful deploy, register the Telegram webhook once:

   ```bash
   railway run python manage.py telegram_set_webhook --url https://<your-domain>
   ```

   It calls `setWebhook` for `https://<domain>/api/v1/telegram/webhook` with
   `TELEGRAM_WEBHOOK_SECRET` as `secret_token` and never prints the bot token. Re-run it
   if the domain changes. **Never run `telegram_poll` against the production bot**: it
   deletes the webhook. Use a separate dev bot locally.
6. Create an admin: `railway run python manage.py createsuperuser`.

Variables (`config.settings.prod`):

| Variable | Required | Notes |
|---|---|---|
| `DJANGO_SETTINGS_MODULE` | yes | `config.settings.prod` (also the image default) |
| `DJANGO_SECRET_KEY` | yes | long random value; startup fails without it |
| `DATABASE_URL` | yes | from the Postgres plugin |
| `REDIS_URL` | yes | from the Redis plugin (Celery broker/results, Channels) |
| `TOKEN_ENCRYPTION_KEY` | yes | Fernet key; must never change once tokens are stored |
| `DJANGO_ALLOWED_HOSTS` | if custom domain | comma-separated; `RAILWAY_PUBLIC_DOMAIN` is added automatically |
| `CSRF_TRUSTED_ORIGINS` | if custom domain | e.g. `https://api.example.com`; the Railway domain is added automatically |
| `RAILWAY_PUBLIC_DOMAIN` | automatic | injected by Railway |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_WEBHOOK_SECRET` | yes for Telegram | `TELEGRAM_BOT_USERNAME` too |
| `FIREBASE_CREDENTIALS_JSON` | yes for push | whole service-account JSON; alternative `FIREBASE_CREDENTIALS_FILE` |
| `CLOUDINARY_URL` | strongly recommended | report attachments; Railway disks are ephemeral, so without it uploads are lost on redeploy |
| `CORS_ALLOWED_ORIGINS` | optional | the mobile app needs none |
| `MOODLE_BASE_URL`, `MOODLE_SERVICE` | optional | defaults to AOU Egypt |
| `SIS_INGEST_ENABLED` | optional | `false` by default; enables `POST /me/sis/ingest` (404 otherwise) |
| `SIS_API_BASE_URL`, `SIS_APP_USER_ID`, `SIS_APP_USERNAME`, `SIS_APP_PASSWORD`, `SIS_BRANCH_ID` | yes for SIS | see `.env.example` |
| `APP_MIN_SUPPORTED_VERSION`, `APP_LATEST_VERSION`, `APP_PRIVACY_URL`, `APP_SUPPORT_TELEGRAM` | optional | `GET /meta/app` |
| `SECURE_SSL_REDIRECT`, `SECURE_HSTS_SECONDS`, `SECURE_HSTS_INCLUDE_SUBDOMAINS`, `SECURE_HSTS_PRELOAD` | optional | defaults: true, 30 days, false, false (subdomains/preload only on your own domain) |
| `LOG_LEVEL`, `DJANGO_LOG_LEVEL` | optional | default `INFO`; logs go to stdout, credentials scrubbed |
| Tuning (`MOODLE_SYNC_INTERVAL_MINUTES`, `SIS_SYNC_INTERVAL_MINUTES`, `REMINDER_*`, `*_HTTP_TIMEOUT_SECONDS`, `TELEGRAM_LINK_TOKEN_TTL_MINUTES`, `DEFAULT_TIMEZONE`) | optional | see `.env.example` |

Build locally: `docker build -t zakerni-backend ./backend` (from the repo root).

## API docs

With the dev server running:

- Swagger UI: http://localhost:8000/api/docs/
- Redoc: http://localhost:8000/api/redoc/
- Raw OpenAPI schema: http://localhost:8000/api/schema/

Regenerate and validate the schema file without running the server:

```bash
python manage.py spectacular --file schema.yaml --validate
```

## Tests, lint, types

```bash
pytest
ruff check .
ruff format --check .
mypy                                  # services, protocols, channels, integrations (pyproject.toml)
python manage.py makemigrations --check --dry-run
```

External clients are never called in tests: `conftest.py` swaps the container's
Moodle, FCM and Telegram clients for in-memory fakes for every test.
One dispatch test (real multi-thread row locking) only runs against PostgreSQL.

## Admin

The admin theme (indigo palette, IBM Plex Sans Arabic, custom login and dashboard) lives in `static/admin/zakerni.css`, `static/fonts`, `templates/admin/` and the `UNFOLD` dict in `config/settings/base.py` (see docs/07-design-system.md, section 5b). `collectstatic` must include it.

`/admin/` (Unfold, Arabic and English via the language switcher). Dashboard with KPI
cards, reminders sent per day (14 days) and the last 10 failed syncs; reports with
attachments, device info, a live conversation with a send box (WebSocket), the inline
reply fallback (both pushed to the student) and status actions;
broadcasts with recipients preview and "Send now" (recipient column and audience filter);
"Send notification" on a user page, or as a list action with exactly one user selected, messages
one user in Arabic and/or English through push and Telegram; read-only sync and delivery logs.
The Moodle token is never displayed.

Moodle sync keeps only current-term courses ("In progress", date-filter fallback) and
also imports online Teams lectures from the Moodle calendar (docs/01 section 4.2). For each
course it also stores the student's group and tutor on `Enrollment.group_name` / `tutor_name`
(`core_group_get_course_user_groups` + `core_enrol_get_enrolled_users` with `groupid`; members
with a non-`student` role). This lookup is best effort and never fails the sync.

## Endpoints

Base path: `/api/v1/`. JWT (`Authorization: Bearer <access>`) unless marked public.
Errors always use `{"error": {"code", "message", "details"}}`. Full contract: `../docs/05-api-spec.md`.

| Method | Path | Notes |
|---|---|---|
| GET | `/health/` | Public smoke test |
| GET | `/meta/app` | Public: versions, privacy URL, support Telegram |
| POST | `/auth/login` | Public. `{username, password}` -> `{access, refresh, user, is_new}`; 5/min per IP; password never stored or logged |
| POST | `/auth/refresh` | Public. `{refresh}` -> `{access, refresh}` |
| POST | `/auth/logout` | `{refresh, fcm_token?}` -> `204`; blacklists refresh, deactivates the device |
| GET / PATCH / DELETE | `/me` | Profile; `{language?, timezone?}`; delete cascades (reports anonymised) |
| GET | `/me/lms` | `{status, last_synced_at, last_sync_error}` |
| POST | `/me/lms/sync` | `202`; 1 per 5 min; `lms_token_expired` if expired |
| GET / POST | `/items` | Range query `from` (or `now`), `to?` (<= 62 days, default 62), `type?`, `course?`; POST creates an exam |
| GET / PATCH / DELETE | `/items/{id}` | Edit/delete manual exams only (`item_not_editable`) |
| PATCH | `/items/{id}/mute` | `{is_muted}` |
| PUT / DELETE | `/items/{id}/reminders` | Per-item offsets override / back to the type rule |
| GET / POST | `/lectures` | Weekly lecture schedules; every future occurrence up to `ends_on` generated on create/edit |
| PATCH / DELETE | `/lectures/{id}` | Future occurrences regenerated / removed |
| GET | `/courses` | `[{id, code, name, is_muted, upcoming_count}]` |
| GET | `/courses/{id}` | Course detail: `group_name`, `tutor_name`, next 30 days of items, lecture schedules |
| PATCH | `/courses/{id}` | `{is_muted}` |
| GET | `/reminder-rules` | Always 4 rules (quiz, tma, exam, lecture) |
| PUT | `/reminder-rules/{type}` | `{offsets_minutes, push_enabled, telegram_enabled}` |
| POST | `/reminder-rules/confirm-defaults` | Onboarding step, `204` |
| POST | `/devices` | FCM token upsert (`201` new / `200` existing) |
| DELETE | `/devices/{fcm_token}` | Deactivate |
| GET / DELETE | `/telegram` | Link status / unlink |
| POST | `/telegram/link` | One-time deep link `{url, expires_at}` (10 min) |
| POST | `/telegram/webhook` | Public, requires `X-Telegram-Bot-Api-Secret-Token` |
| GET | `/notifications` | History, cursor paginated |
| GET | `/notifications/unread-count` | `{count}` |
| POST | `/notifications/mark-read` | `{ids?}` (empty = all) |
| GET | `/reports/categories` | Translated `[{code, label}]` |
| GET / POST | `/reports` | Mine / create (multipart, <= 3 images of 5 MB; 10 per day) |
| GET | `/reports/{id}` | With replies |
| POST | `/reports/{id}/replies` | Student follow-up |

## Apps

`core` (base models, error envelope, pagination, throttles, Fernet crypto, log
scrubbing, admin dashboard, `compile_po`, Python 3.14 template-context shim),
`accounts` (User, auth, profile), `moodle` (clients, `MoodleAccount`, `SyncLog`, sync),
`schedule` (courses, enrollments, items, lecture schedules), `reminders` (rules,
overrides, scheduling, dispatch, messages), `notifications` (devices, Telegram linking,
channels, history), `support` (reports), `broadcasts` (admin broadcasts).
