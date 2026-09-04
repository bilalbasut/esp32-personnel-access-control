import os
from datetime import timedelta
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
    "django.contrib.auth",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.admin",
    "corsheaders",
    "rest_framework",
    "rest_framework_simplejwt.token_blacklist",  # logout'ta refresh token'ı geçersiz kılmak için
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
    # SessionAuthentication sadece admin login/browsable API için, Vue frontend JWT kullanır.
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework_simplejwt.authentication.JWTAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",  # login/refresh/logout kendi AllowAny'sini override eder
    ],
    "UNAUTHENTICATED_USER": None,
    # Kapalı: DRF'in ?format= param'ı bu projenin ?format=csv ile çakışıp PdksReportView'ı 404'letiyordu.
    "URL_FORMAT_OVERRIDE": None,
}

# Access token stateless, kısa ömürlü (15dk) - logout'ta geri alınamaz, en kötü 15dk geçerli kalır.
# Refresh token rotate+blacklist ile korunur (bkz. LogoutView).
SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=15),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "UPDATE_LAST_LOGIN": True,
    "AUTH_HEADER_TYPES": ("Bearer",),
    "USER_ID_FIELD": "id",
    "USER_ID_CLAIM": "user_id",
}

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
]

CORS_ALLOW_ALL_ORIGINS = True  # cookie/session auth'u zayıflatacak bir şey yok, session sadece admin login için

# django.request'i mail_admins'ten console'a yönlendirir: Python 3.14'te AdminEmailHandler'ın
# traceback render'ı her 500'de crash ediyordu (Context.__copy__ super() uyumsuzluğu).
# Sentry gibi gerçek hata takibi istenirse eklenecek yer burası.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "console": {"class": "logging.StreamHandler"},
    },
    "loggers": {
        "django.request": {
            "handlers": ["console"],
            "level": "ERROR",
            "propagate": False,
        },
    },
}

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

# Sadece django.contrib.admin'in template'leri için, başka server-render sayfa yok.
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

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"  # raporlar REPORT_TZ ile açıkça çevirir, session timezone'una güvenmez
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
