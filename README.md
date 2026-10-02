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

Beat schedule (`config/settings/base.py`):

| Task | Schedule |
|---|---|
| `moodle.enqueue_moodle_syncs` | every `MOODLE_SYNC_INTERVAL_MINUTES` (30), jittered per account |
| `reminders.dispatch_due_reminders` | every minute |
| `schedule.expand_lecture_schedules` | daily 00:10 Cairo |
| `reminders.cleanup` / `notifications.cleanup_link_tokens` | daily 03:00 / 03:05 Cairo |

External services: set `FIREBASE_CREDENTIALS_FILE` (service-account JSON) for push and
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
- `prod.py` — HTTPS/HSTS hardening, explicit CORS allow-list.

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

`/admin/` (Unfold, Arabic and English via the language switcher). Dashboard with KPI
cards, reminders sent per day (14 days) and the last 10 failed syncs; reports with
attachments, device info, a live conversation with a send box (WebSocket), the inline
reply fallback (both pushed to the student) and status actions;
broadcasts with recipients preview and "Send now"; read-only sync and delivery logs.
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
