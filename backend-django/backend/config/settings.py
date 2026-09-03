import os
from pathlib import Path
from dotenv import load_dotenv

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# Load environment variables from .env (checks backend dir, then project root)
load_dotenv(BASE_DIR / '.env')
load_dotenv(BASE_DIR.parent / '.env')

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "change-me-in-production")
DEBUG = os.environ.get("DJANGO_DEBUG", "1") == "1"
ALLOWED_HOSTS = os.environ.get("DJANGO_ALLOWED_HOSTS", "*").split(",")

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.staticfiles",
    # Added for real operator identity/audit (previously this API had no
    # user model at all). auth+sessions+messages+admin is the standard
    # bundle admin.site needs - see TEMPLATES below, which admin also
    # requires and this project didn't have until now.
    "django.contrib.auth",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.admin",
    "corsheaders",
    "rest_framework",
    "rest_framework.authtoken",
    "core",
    "devices",
    "cards",
    "accounts",
]

AUTH_USER_MODEL = "accounts.Operator"

REST_FRAMEWORK = {
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
        "rest_framework.renderers.BrowsableAPIRenderer",
    ],
    "DEFAULT_PARSER_CLASSES": [
        "rest_framework.parsers.JSONParser",
        "rest_framework.parsers.MultiPartParser",
        "rest_framework.parsers.FormParser",
    ],
    # Recognizes a logged-in Operator (via POST /api/auth/login token, or
    # an admin session cookie) when one is sent, so request.user is real
    # and audit logging can record who did what - see accounts/audit.py.
    # Endpoints are NOT locked behind login yet (still effectively AllowAny
    # by DRF's own default): the Vue frontend doesn't send credentials yet,
    # and flipping DEFAULT_PERMISSION_CLASSES to IsAuthenticated today would
    # just break every existing request. Do that once the frontend rewrite
    # logs operators in - until then, request.user is Operator-or-None and
    # audit entries record "system" for anonymous requests.
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.TokenAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ],
    "UNAUTHENTICATED_USER": None,
    # Disabled: DRF's own ?format= query param (used to pick JSON vs the
    # browsable API) collides with this project's *own* ?format=csv param
    # on /api/reports/pdks (core/views.py PdksReportView) - with this on,
    # DRF's content negotiation sees "csv", finds no renderer registered
    # for it, and 404s before the view ever runs. Nothing else in this
    # project relies on the ?format= override, so turning it off is safe.
    "URL_FORMAT_OVERRIDE": None,
}

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
]

# Mirrors server.js's app.use(cors()) - wide open. The API itself still has
# no cookie/session auth for CORS to weaken; sessions now exist only to
# support the Django admin login form.
CORS_ALLOW_ALL_ORIGINS = True

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

# Only needed for django.contrib.admin's own templates - this project has
# no other server-rendered pages. APP_DIRS picks up each app's
# templates/ automatically if any app ever needs its own.
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
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

# Now live: this governs Operator passwords (admin login, createsuperuser,
# password resets) now that django.contrib.auth is installed. The API's
# own resources (cards/devices/employees) still have no user-facing auth -
# see the REST_FRAMEWORK comment above.
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

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
