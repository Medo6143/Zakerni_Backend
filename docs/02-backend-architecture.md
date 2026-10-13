# 02 — Backend Architecture (Django)

Modular monolith with clean layering inside each app. Inspired by the HackSoft Django Styleguide, adapted to SOLID with explicit protocols for external dependencies.

## 1. Layers

```
HTTP / Celery / Admin          (delivery)      api/views.py, tasks.py, admin.py
        │
        ▼
Services  (write use cases)    selectors (reads)
        │                            │
        ▼                            ▼
Protocols (ports)  ◄── implemented by ── Integrations (Moodle, FCM, Telegram)
        │
        ▼
Models (persistence)  →  PostgreSQL
```

Dependency rule: arrows point inward. Views know services; services know models and protocols; services never import views, serializers, `request`, or concrete clients.

| Layer | Allowed | Forbidden |
|---|---|---|
| `api/views.py` | parse request, call one service/selector, return serializer data | ORM queries, business rules |
| `api/serializers.py` | validation, shaping output | DB writes, external calls |
| `services/` | business rules, transactions, calling protocols | `request`, HTTP responses |
| `selectors.py` | read queries (`select_related`, filters) | writes |
| `models.py` | fields, constraints, trivial properties | business logic, external calls |
| `tasks.py` | load ids, call a service | logic |
| `integrations/` | concrete clients behind protocols | business rules |

## 2. Folder structure

```
backend/
├── manage.py
├── pyproject.toml                 # ruff, mypy, pytest config
├── requirements/
│   ├── base.txt
│   ├── dev.txt
│   └── prod.txt
├── locale/
│   ├── ar/LC_MESSAGES/django.po
│   └── en/LC_MESSAGES/django.po
├── config/
│   ├── settings/{base,dev,test,prod}.py
│   ├── urls.py                    # /admin/, /api/v1/, /api/schema/
│   ├── celery.py                  # app + beat schedule
│   ├── container.py               # wires protocols -> implementations
│   └── wsgi.py / asgi.py
└── apps/
    ├── core/                      # shared: base models, errors, pagination, i18n helpers, crypto
    │   ├── models.py              # TimeStampedModel, UUIDModel
    │   ├── exceptions.py          # DomainError, ApplicationError -> error envelope
    │   ├── crypto.py              # encrypt()/decrypt() with Fernet
    │   └── api/                   # exception handler, pagination
    ├── accounts/                  # User, auth, profile, account deletion
    │   ├── models.py
    │   ├── services/{auth.py, app_auth.py, profile.py}   # app_auth: register / sign in / change password / temporary password
    │   ├── selectors.py
    │   ├── api/{serializers,views,urls}.py
    │   └── tests/
    ├── moodle/                    # MoodleAccount, SyncLog, sync use case
    │   ├── protocols.py           # MoodleAuthClient, MoodleDataClient
    │   ├── integrations/
    │   │   ├── http_client.py     # HttpMoodleClient (httpx)
    │   │   ├── payload_client.py  # PayloadMoodleClient: data the phone fetched (phone-side fetch)
    │   │   └── fake_client.py     # FakeMoodleClient (tests / local demo)
    │   ├── services/{sync.py, ingest.py, mappers.py}   # ingest.py: POST /me/lms/ingest use case
    │   ├── tasks.py
    │   └── tests/
    ├── schedule/                  # Course, Enrollment, Item, LectureSchedule
    │   ├── models.py
    │   ├── services/{items.py, lectures.py, courses.py}
    │   ├── selectors.py           # items_in_range(user, start, end)
    │   ├── api/
    │   ├── tasks.py               # expand_lecture_schedules
    │   └── tests/
    ├── reminders/                 # ReminderRule, ItemReminderOverride, ScheduledReminder
    │   ├── defaults.py            # DEFAULT_RULES per item type (single registry)
    │   ├── protocols.py           # ReminderScheduler (used by schedule/moodle/notifications)
    │   ├── services/{rules.py, scheduling.py, dispatch.py, messages.py, cleanup.py}
    │   ├── api/
    │   ├── tasks.py               # dispatch_due_reminders, cleanup
    │   └── tests/
    ├── notifications/             # Device, TelegramLink(+Token), Notification (history), channels
    │   ├── protocols.py           # NotificationChannel, Message, DeliveryResult, PushSender, TelegramBotClient
    │   ├── channels/{fcm.py, telegram.py, registry.py, fake.py}
    │   ├── integrations/{fcm_sender.py, telegram_client.py, fakes.py}  # firebase-admin / httpx behind the protocols
    │   ├── services/{devices.py, telegram_linking.py, history.py, cleanup.py}
    │   ├── api/                   # devices, telegram link + webhook, history
    │   └── tests/
    ├── support/                   # Report, ReportAttachment, ReportReply
    │   ├── services/reports.py
    │   ├── api/
    │   ├── admin.py
    │   └── tests/
    └── broadcasts/                # Broadcast
        ├── services/send.py
        ├── tasks.py
        └── admin.py               # "Send" action
```

## 3. SOLID examples

### Protocols (DIP, ISP)

```python
# apps/moodle/protocols.py
class MoodleAuthClient(Protocol):
    def get_token(self, username: str, password: str) -> str: ...

class MoodleDataClient(Protocol):
    def site_info(self, token: str) -> SiteInfo: ...
    def courses(self, token: str, moodle_user_id: int) -> list[MoodleCourse]: ...
    def quizzes(self, token: str, course_ids: list[int]) -> list[MoodleQuiz]: ...
    def assignments(self, token: str, course_ids: list[int]) -> list[MoodleAssignment]: ...
```

### Service depending on abstractions

```python
# apps/moodle/services/sync.py
@dataclass(frozen=True)
class SyncMoodleAccount:
    client: MoodleDataClient
    scheduler: ReminderScheduler          # protocol from reminders app

    def __call__(self, account: MoodleAccount) -> SyncResult:
        ...
```

```python
# config/container.py  (the only place that knows concrete classes)
def sync_moodle_account() -> SyncMoodleAccount:
    channels = notification_channels()          # registry wired to FCM + Telegram clients
    return SyncMoodleAccount(client=moodle_client(),
                             scheduler=ReminderSchedulingService(channels=channels),
                             channels=channels)
```

Services that change items, rules, overrides, mutes, devices or the Telegram link
receive a `ReminderScheduler` argument and call it explicitly (no signals). Views and
tasks get ready-made instances from `config/container.py`; tests swap only the
external clients (`moodle_client`, `push_sender`, `telegram_bot_client`) for fakes.

### Channels (OCP, LSP)

```python
# apps/notifications/channels/registry.py
CHANNELS: dict[str, NotificationChannel] = {
    FcmChannel.code: FcmChannel(),
    TelegramChannel.code: TelegramChannel(),
}
```

The dispatcher iterates the registry. It never checks `if channel == "telegram"`.

### Item type registry (OCP)

```python
# apps/reminders/defaults.py
DEFAULT_RULES = {
    ItemType.QUIZ:    RuleDefault(offsets=[1440, 180],  channels={"push", "telegram"}),
    ItemType.TMA:     RuleDefault(offsets=[4320, 1440], channels={"push", "telegram"}),
    ItemType.EXAM:    RuleDefault(offsets=[4320, 1440], channels={"push", "telegram"}),
    ItemType.LECTURE: RuleDefault(offsets=[30],         channels={"push"}),
}
```

### Phone-side fetch (DIP in practice)

`SyncMoodleAccount` and `SyncSisAccount` depend only on `MoodleDataClient` / `SisClient`. The ingest endpoints build a `PayloadMoodleClient` / `PayloadSisClient` from the validated request body and `config.container.sync_moodle_account_with(client)` / `sync_sis_account_with(client)` wire the unchanged services around it; nothing is duplicated and nothing calls Moodle or the SIS. Settings: `SIS_INGEST_ENABLED` (default `false`). Accounts without a stored token (Moodle) or password (SIS) are skipped by the periodic tasks.

## 4. Errors

```python
class ApplicationError(Exception):
    code: str = "application_error"
    status: int = 400
    message = _("Something went wrong.")
```

Subclasses: `InvalidLmsCredentials`, `LmsUnavailable`, `LmsTokenExpired`, `TelegramLinkExpired`, `ItemNotEditable` (Moodle items cannot be edited, only overridden/muted). A DRF exception handler converts them to:

```json
{"error": {"code": "invalid_lms_credentials", "message": "اسم المستخدم أو كلمة المرور غير صحيحة", "details": {}}}
```

## 5. Libraries

| Purpose | Library |
|---|---|
| API | `djangorestframework`, `drf-spectacular` |
| Auth | `djangorestframework-simplejwt` |
| Settings | `django-environ` |
| Async jobs | `celery[redis]` |
| HTTP | `httpx` |
| Crypto | `cryptography` (Fernet) |
| Push | `firebase-admin` |
| Admin | `django-unfold` |
| Postgres | `psycopg[binary]` |
| Files | `Pillow` (validate report images) |
| Dev | `ruff`, `mypy`, `django-stubs`, `pytest`, `pytest-django`, `factory_boy`, `freezegun` |

## 6. Testing strategy

- Services: unit tests with `FakeMoodleClient` and a `FakeChannel` that records sends.
- Scheduling: table-driven tests with `freezegun` (offsets, mutes, overrides, past items, reschedule on change).
- Dispatch: concurrency test (two workers, no double send), retry and skip-late behaviour.
- API: one test per endpoint for success, validation error, auth error.
- Telegram webhook: token valid / expired / reused.
