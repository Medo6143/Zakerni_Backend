"""Production settings (Railway or any HTTPS reverse proxy / PaaS).

Everything comes from the environment. Railway injects ``DATABASE_URL`` and
``REDIS_URL`` from its Postgres/Redis plugins (read in base.py) and
``RAILWAY_PUBLIC_DOMAIN`` for the generated public domain.
"""

from .base import *  # noqa: F401,F403
from .base import LOGGING, MIDDLEWARE, STORAGES, env

DEBUG = False

SECRET_KEY = env("DJANGO_SECRET_KEY")  # required: no insecure default in production

# --- Hosts / CSRF -------------------------------------------------------------
RAILWAY_PUBLIC_DOMAIN = env("RAILWAY_PUBLIC_DOMAIN", default="")
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=[])
CSRF_TRUSTED_ORIGINS = env.list("CSRF_TRUSTED_ORIGINS", default=[])
if RAILWAY_PUBLIC_DOMAIN:
    if RAILWAY_PUBLIC_DOMAIN not in ALLOWED_HOSTS:
        ALLOWED_HOSTS.append(RAILWAY_PUBLIC_DOMAIN)
    railway_origin = f"https://{RAILWAY_PUBLIC_DOMAIN}"
    if railway_origin not in CSRF_TRUSTED_ORIGINS:
        CSRF_TRUSTED_ORIGINS.append(railway_origin)
# Railway's internal healthcheck sends Host: healthcheck.railway.app.
ALLOWED_HOSTS.append("healthcheck.railway.app")

# --- HTTPS behind the proxy (Railway terminates TLS) -----------------------------
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = env.bool("SECURE_SSL_REDIRECT", default=True)
# The healthcheck is plain HTTP from inside Railway; never redirect it.
SECURE_REDIRECT_EXEMPT = [r"^api/v1/health/$"]
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = env.int("SECURE_HSTS_SECONDS", default=60 * 60 * 24 * 30)
# Off by default: *.up.railway.app is a shared parent domain. Enable on your own domain.
SECURE_HSTS_INCLUDE_SUBDOMAINS = env.bool("SECURE_HSTS_INCLUDE_SUBDOMAINS", default=False)
SECURE_HSTS_PRELOAD = env.bool("SECURE_HSTS_PRELOAD", default=False)
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"

CORS_ALLOW_ALL_ORIGINS = False
CORS_ALLOWED_ORIGINS = env.list("CORS_ALLOWED_ORIGINS", default=[])

# --- Static files (admin) via WhiteNoise -------------------------------------
MIDDLEWARE = [
    MIDDLEWARE[0],  # SecurityMiddleware
    "whitenoise.middleware.WhiteNoiseMiddleware",
    *MIDDLEWARE[1:],
]
STORAGES = {
    **STORAGES,
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

# --- Logging: stdout only (Railway collects it), credentials scrubbed ----------------
LOGGING = {
    **LOGGING,
    "root": {"handlers": ["console"], "level": env("LOG_LEVEL", default="INFO")},
}
