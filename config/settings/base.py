"""Base Django settings for the Zakerni backend, shared by all environments."""

from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import environ
from celery.schedules import crontab
from django.utils.translation import gettext_lazy as _

BASE_DIR = Path(__file__).resolve().parent.parent.parent

env = environ.Env(
    DEBUG=(bool, False),
)
environ.Env.read_env(str(BASE_DIR / ".env"))

SECRET_KEY = env("DJANGO_SECRET_KEY", default="insecure-dev-key-change-me")
DEBUG = env.bool("DJANGO_DEBUG", default=False)
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=["*"])

DJANGO_APPS = [
    # daphne first: ``runserver`` then serves ASGI (HTTP + WebSocket).
    "daphne",
    "unfold",
    "unfold.contrib.filters",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
]

THIRD_PARTY_APPS = [
    "channels",
    "rest_framework",
    "rest_framework_simplejwt",
    "rest_framework_simplejwt.token_blacklist",
    "drf_spectacular",
    "corsheaders",
    "django_filters",
]

LOCAL_APPS = [
    "apps.core",
    "apps.accounts",
    "apps.moodle",
    "apps.sis",
    "apps.schedule",
    "apps.reminders",
    "apps.notifications",
    "apps.support",
    "apps.broadcasts",
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

DATABASES = {
    "default": env.db("DATABASE_URL", default="postgres://zakerni:zakerni@localhost:5432/zakerni"),
}

AUTH_USER_MODEL = "accounts.User"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# --- i18n -------------------------------------------------------------
LANGUAGE_CODE = "en"
LANGUAGES = [
    ("ar", "العربية"),
    ("en", "English"),
]
LOCALE_PATHS = [BASE_DIR / "locale"]
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

# Uploaded files (report attachments): Cloudinary when CLOUDINARY_URL is set (the SDK
# reads it from the environment), otherwise the local MEDIA_ROOT.
CLOUDINARY_URL = env("CLOUDINARY_URL", default="")
STORAGES = {
    "default": {
        "BACKEND": (
            "apps.core.storage.CloudinaryMediaStorage"
            if CLOUDINARY_URL
            else "django.core.files.storage.FileSystemStorage"
        ),
    },
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- DRF ----------------------------------------------------------------
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": ("rest_framework.permissions.IsAuthenticated",),
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "EXCEPTION_HANDLER": "apps.core.api.exceptions.zakerni_exception_handler",
    "DEFAULT_PAGINATION_CLASS": "apps.core.api.pagination.CursorSetPagination",
    "PAGE_SIZE": 20,
    "DEFAULT_THROTTLE_RATES": {
        "login": "5/min",
        "lms_sync": "1/5m",  # parsed by apps.core.api.throttling (multi-unit periods)
        "sis_sync": "1/5m",
        "report_create": "10/day",
    },
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=30),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=30),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "AUTH_HEADER_TYPES": ("Bearer",),
    "USER_ID_FIELD": "id",
    "USER_ID_CLAIM": "user_id",
}

SPECTACULAR_SETTINGS = {
    "TITLE": "Zakerni API",
    "DESCRIPTION": (
        "Backend API for the Zakerni (ذكّرني) student reminder app.\n\n"
        "**Real-time report chat (WebSocket, not described by OpenAPI).** "
        "Connect to `ws://<host>/ws/v1/reports/<report_id>/?token=<JWT access token>` "
        "(admin pages use the session cookie instead). Only the report owner or staff may "
        "join: close code `4401` = missing/invalid/expired token, `4403` = not allowed. "
        'Send `{"type": "message", "body": "<text>"}`; everyone in the thread receives '
        '`{"type": "reply.created", "reply": <ReportReply>}` (same shape as in '
        "`GET /reports/{id}`), also for replies posted through REST or the admin. "
        'Validation problems come back as `{"type": "error", "error": {"code", "message", '
        '"details"}}`. See docs/05-api-spec.md.'
    ),
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "SCHEMA_PATH_PREFIX": "/api/v1",
    "COMPONENT_SPLIT_REQUEST": True,
    "ENUM_NAME_OVERRIDES": {
        "ItemTypeEnum": "apps.schedule.models.ItemType",
        "ItemSourceEnum": "apps.schedule.models.ItemSource",
        "ItemStatusEnum": "apps.schedule.models.ItemStatus",
        "ReportStatusEnum": "apps.support.models.Report.Status",
        "ReportCategoryEnum": "apps.support.models.Report.Category",
        "NotificationKindEnum": "apps.notifications.models.Notification.Kind",
        "DevicePlatformEnum": "apps.notifications.models.Device.Platform",
        "LmsStatusEnum": "apps.moodle.models.MoodleAccount.Status",
        "SisStatusEnum": "apps.sis.models.SisAccount.Status",
        "LanguageEnum": "apps.accounts.models.User.Language",
    },
    "TAGS": [
        {"name": "auth", "description": "LMS login and JWT tokens"},
        {"name": "me", "description": "Current user profile and LMS status"},
        {"name": "sis", "description": "Student information system connection and sync"},
        {"name": "items", "description": "Calendar items (quizzes, TMAs, exams, lectures)"},
        {"name": "lectures", "description": "Recurring lecture schedules"},
        {"name": "courses", "description": "Courses and per-course mute"},
        {"name": "reminders", "description": "Reminder rules and per-item overrides"},
        {"name": "devices", "description": "FCM device registration"},
        {"name": "telegram", "description": "Telegram linking and bot webhook"},
        {"name": "notifications", "description": "Notification history"},
        {"name": "reports", "description": "Support reports"},
        {"name": "meta", "description": "App metadata and health"},
    ],
}

CORS_ALLOW_ALL_ORIGINS = env.bool("CORS_ALLOW_ALL_ORIGINS", default=True)

# --- Channels (WebSocket report chat) -------------------------------------------
CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {"hosts": [env("REDIS_URL", default="redis://localhost:6379/0")]},
    },
}

# --- Celery ---------------------------------------------------------------
CELERY_BROKER_URL = env("REDIS_URL", default="redis://localhost:6379/0")
CELERY_RESULT_BACKEND = env("REDIS_URL", default="redis://localhost:6379/0")
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TIMEZONE = "UTC"

DEFAULT_TIMEZONE = env("DEFAULT_TIMEZONE", default="Africa/Cairo")


def local_now() -> datetime:
    """``nowfun`` for crontab entries expressed in local (Cairo) time. Module-level
    so the beat scheduler can pickle it by reference."""
    return datetime.now(ZoneInfo(DEFAULT_TIMEZONE))


MOODLE_SYNC_INTERVAL_MINUTES = env.int("MOODLE_SYNC_INTERVAL_MINUTES", default=30)

SIS_SYNC_INTERVAL_MINUTES = env.int("SIS_SYNC_INTERVAL_MINUTES", default=360)

CELERY_BEAT_SCHEDULE: dict = {
    "enqueue-sis-syncs": {
        "task": "sis.enqueue_sis_syncs",
        "schedule": timedelta(minutes=SIS_SYNC_INTERVAL_MINUTES),
    },
    "enqueue-moodle-syncs": {
        "task": "moodle.enqueue_moodle_syncs",
        "schedule": timedelta(minutes=MOODLE_SYNC_INTERVAL_MINUTES),
    },
    "dispatch-due-reminders": {
        "task": "reminders.dispatch_due_reminders",
        "schedule": crontab(),  # every minute
    },
    "expand-lecture-schedules": {
        "task": "schedule.expand_lecture_schedules",
        "schedule": crontab(hour=0, minute=10, nowfun=local_now),
    },
    "cleanup-reminders": {
        "task": "reminders.cleanup",
        "schedule": crontab(hour=3, minute=0, nowfun=local_now),
    },
    "cleanup-telegram-link-tokens": {
        "task": "notifications.cleanup_link_tokens",
        "schedule": crontab(hour=3, minute=5, nowfun=local_now),
    },
}

# --- Zakerni / Fernet crypto ------------------------------------------
# Name kept as TOKEN_ENCRYPTION_KEY in .env to match docs/08 + .env.example.
FERNET_KEY = env("TOKEN_ENCRYPTION_KEY", default="")

# --- Moodle ---------------------------------------------------------------
MOODLE_BASE_URL = env("MOODLE_BASE_URL", default="https://egylms.arabou.edu.kw")
MOODLE_SERVICE_NAME = env("MOODLE_SERVICE", default="moodle_mobile_app")
MOODLE_HTTP_TIMEOUT_SECONDS = env.float("MOODLE_HTTP_TIMEOUT_SECONDS", default=10.0)
# Optional egress proxy for Moodle calls; defaults to the SIS proxy (declared below it
# is read from the same env var). Empty = direct connection.
MOODLE_PROXY_URL = env.str("MOODLE_PROXY_URL", default=env.str("SIS_PROXY_URL", default=""))

# --- SIS (AOU Egypt Student Information System) ---------------------------------
# All values come from the environment (see .env.example); the app-level values are
# the public web client's configuration and are never hard-coded here.
SIS_API_BASE_URL = env("SIS_API_BASE_URL", default="")
SIS_APP_USER_ID = env("SIS_APP_USER_ID", default="")
SIS_APP_USERNAME = env("SIS_APP_USERNAME", default="")
SIS_APP_PASSWORD = env("SIS_APP_PASSWORD", default="")
SIS_BRANCH_ID = env.int("SIS_BRANCH_ID", default=5)
SIS_HTTP_TIMEOUT_SECONDS = env.float("SIS_HTTP_TIMEOUT_SECONDS", default=10.0)
# Optional egress proxy for every SIS call (e.g. an Egypt-based proxy, because the
# server is hosted abroad). Empty = direct connection. Example: http://user:pass@host:port
SIS_PROXY_URL = env.str("SIS_PROXY_URL", default="")

# --- Reminders ---------------------------------------------------------------
REMINDER_DISPATCH_BATCH_SIZE = env.int("REMINDER_DISPATCH_BATCH_SIZE", default=500)
REMINDER_MAX_ATTEMPTS = env.int("REMINDER_MAX_ATTEMPTS", default=3)
REMINDER_RETRY_DELAY_MINUTES = env.int("REMINDER_RETRY_DELAY_MINUTES", default=2)
REMINDER_SKIP_LATE_MINUTES = env.int("REMINDER_SKIP_LATE_MINUTES", default=30)
REMINDER_HISTORY_RETENTION_DAYS = env.int("REMINDER_HISTORY_RETENTION_DAYS", default=90)

# --- Telegram ---------------------------------------------------------------
TELEGRAM_BOT_TOKEN = env("TELEGRAM_BOT_TOKEN", default="")
TELEGRAM_BOT_USERNAME = env("TELEGRAM_BOT_USERNAME", default="ZakerniBot")
TELEGRAM_WEBHOOK_SECRET = env("TELEGRAM_WEBHOOK_SECRET", default="")
TELEGRAM_LINK_TOKEN_TTL_MINUTES = env.int("TELEGRAM_LINK_TOKEN_TTL_MINUTES", default=10)
TELEGRAM_HTTP_TIMEOUT_SECONDS = env.float("TELEGRAM_HTTP_TIMEOUT_SECONDS", default=10.0)

# --- Firebase / FCM ---------------------------------------------------------
FIREBASE_CREDENTIALS_FILE = env("FIREBASE_CREDENTIALS_FILE", default="")
# Alternative for PaaS hosts without a file system for secrets (Railway): the full
# service-account JSON in one variable. Takes precedence over the file. Never logged.
FIREBASE_CREDENTIALS_JSON = env("FIREBASE_CREDENTIALS_JSON", default="")
FCM_HTTP_TIMEOUT_SECONDS = env.float("FCM_HTTP_TIMEOUT_SECONDS", default=10.0)

# --- Support reports ----------------------------------------------------------
REPORT_MAX_ATTACHMENTS = 3
REPORT_MAX_ATTACHMENT_BYTES = 5 * 1024 * 1024
DATA_UPLOAD_MAX_MEMORY_SIZE = 20 * 1024 * 1024

# --- App meta (GET /meta/app) ----------------------------------------------------
APP_MIN_SUPPORTED_VERSION = env("APP_MIN_SUPPORTED_VERSION", default="1.0.0")
APP_LATEST_VERSION = env("APP_LATEST_VERSION", default="1.0.0")
APP_PRIVACY_URL = env("APP_PRIVACY_URL", default="")
APP_SUPPORT_TELEGRAM = env("APP_SUPPORT_TELEGRAM", default="")

# --- django-unfold admin -----------------------------------------------------------
UNFOLD = {
    "SITE_TITLE": _("Zakerni Admin"),
    "SITE_HEADER": _("Zakerni"),
    "SITE_SYMBOL": "notifications_active",
    "SHOW_LANGUAGES": True,
    "DASHBOARD_CALLBACK": "apps.core.dashboard.dashboard_callback",
}

# --- Logging: never log passwords -------------------------------------
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {
        "scrub_credentials": {
            "()": "apps.core.logging_filters.ScrubCredentialsFilter",
        },
    },
    "formatters": {
        "verbose": {
            "format": "%(asctime)s %(levelname)s %(name)s %(message)s",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "stream": "ext://sys.stdout",
            "formatter": "verbose",
            "filters": ["scrub_credentials"],
        },
    },
    "root": {
        "handlers": ["console"],
        "level": "INFO",
    },
    "loggers": {
        "django": {
            "handlers": ["console"],
            "level": env("DJANGO_LOG_LEVEL", default="INFO"),
            "propagate": False,
        },
        # httpx logs every request URL at INFO; Moodle URLs carry the wstoken (and the
        # login call the password) in the query string, so never log them.
        "httpx": {"level": "WARNING"},
        "httpcore": {"level": "WARNING"},
    },
}
