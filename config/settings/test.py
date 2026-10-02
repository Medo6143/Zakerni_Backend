from .base import *  # noqa: F401,F403

DEBUG = False
FERNET_KEY = "Uc1pKgnMlNfdgh6EI2xzOfCq87LlZ4PIu4yeVCf-Fjc="  # test-only fixed key

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}

CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True

PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

TELEGRAM_WEBHOOK_SECRET = "test-webhook-secret"
TELEGRAM_BOT_USERNAME = "ZakerniBot"
FIREBASE_CREDENTIALS_FILE = ""
FIREBASE_CREDENTIALS_JSON = ""
STORAGES = {
    **STORAGES,  # noqa: F405
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
}
SIMPLE_JWT = {**SIMPLE_JWT, "SIGNING_KEY": "test-signing-key-that-is-long-enough-for-hs256"}  # noqa: F405
CHANNEL_LAYERS = {"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}}
