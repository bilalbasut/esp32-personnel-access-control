import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

# Docker Compose loads .env automatically via env_file: for containers, but
# that mechanism doesn't exist for a bare `python manage.py runserver` on
# the host - without this, every os.environ.get() below silently falls back
# to its hardcoded default instead of raising, which is how a local run
# quietly ended up pointed at the wrong Postgres instance/port.
load_dotenv(BASE_DIR.parent / ".env")

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "change-me-in-production")
DEBUG = os.environ.get("DJANGO_DEBUG", "1") == "1"
ALLOWED_HOSTS = os.environ.get("DJANGO_ALLOWED_HOSTS", "*").split(",")

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.staticfiles",
    "corsheaders",
    "core",
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.common.CommonMiddleware",
]

# Mirrors server.js's app.use(cors()) - wide open, no cookie/session auth on
# this API for CORS to weaken.
CORS_ALLOW_ALL_ORIGINS = True

ROOT_URLCONF = "pdks_project.urls"
WSGI_APPLICATION = "pdks_project.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("DB_NAME", "pdks"),
        "USER": os.environ.get("DB_USER", "pdks"),
        "PASSWORD": os.environ.get("DB_PASSWORD", "pdks_password"),
        "HOST": os.environ.get("DB_HOST", "127.0.0.1"),
        "PORT": os.environ.get("DB_PORT", "5432"),
    }
}

# No user-facing auth in this API today (matches the original server.js,
# which has none either) - kept minimal on purpose.
AUTH_PASSWORD_VALIDATORS = []

LANGUAGE_CODE = "en-us"
# Stored timestamps are UTC (spec 5.3); reports convert explicitly via
# REPORT_TZ instead of relying on Django/Postgres session timezone.
TIME_ZONE = "UTC"
USE_TZ = False

STATIC_URL = "static/"

DEFAULT_AUTO_FIELD = "django.db.models.AutoField"

# --- App-specific settings (read by core/views.py, core/acl.py) ---
MQTT_HOST = os.environ.get("MQTT_HOST", "127.0.0.1")
MQTT_PORT = int(os.environ.get("MQTT_PORT", "1883"))
PANEL_BASE_URL = os.environ.get("PANEL_BASE_URL", "")
TZ_OFFSET_MINUTES = int(os.environ.get("TZ_OFFSET_MINUTES", "180"))
REPORT_TZ = os.environ.get("REPORT_TZ", "Europe/Istanbul")
FIRMWARE_DIR = os.environ.get("FIRMWARE_DIR", str(BASE_DIR / "firmware_files"))
os.makedirs(FIRMWARE_DIR, exist_ok=True)
