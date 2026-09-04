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
    # Gerçek operatör kimliği/audit için eklendi (daha önce bu API'de hiç
    # user modeli yoktu). auth+sessions+messages+admin, admin.site'ın
    # ihtiyaç duyduğu standart paket - aşağıdaki TEMPLATES'e bakın, admin
    # onu da gerektiriyor ve bu proje şimdiye kadar hiç kullanmıyordu.
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
    # Gönderilmişse giriş yapmış bir Operator'ü tanır (POST /api/auth/login
    # token'ı ya da admin session cookie'si üzerinden), böylece request.user
    # gerçek olur ve audit logging kimin ne yaptığını kaydedebilir - bkz.
    # accounts/audit.py. Endpoint'ler henüz login'in arkasına kilitlenmedi
    # (DRF'in kendi default'uyla hâlâ fiilen AllowAny): Vue frontend henüz
    # kimlik bilgisi göndermiyor, DEFAULT_PERMISSION_CLASSES'ı bugün
    # IsAuthenticated'a çevirmek mevcut her isteği kırardı. Frontend yeniden
    # yazımı operatörleri giriş yaptırmaya başladığında bu değiştirilecek -
    # o ana kadar request.user Operator-ya-da-None, anonim istekler için
    # audit kayıtları "system" olarak düşüyor.
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.TokenAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ],
    "UNAUTHENTICATED_USER": None,
    # Kapatıldı: DRF'in kendi ?format= query param'ı (JSON mu browsable API
    # mi seçmek için) bu projenin KENDİ ?format=csv param'ıyla /api/reports/pdks
    # üzerinde çakışıyor (core/views.py PdksReportView) - bu açıkken DRF'in
    # content negotiation'ı "csv"yi görüp ona kayıtlı bir renderer bulamıyor
    # ve view hiç çalışmadan 404 dönüyor. Bu projede başka hiçbir yer ?format=
    # override'ına ihtiyaç duymuyor, o yüzden kapatmak güvenli.
    "URL_FORMAT_OVERRIDE": None,
}

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
]

# server.js'deki app.use(cors())'un aynısı - tamamen açık. API'nin kendisinde
# CORS'un zayıflatabileceği bir cookie/session auth'u zaten yok; session'lar
# şu an sadece Django admin login formunu desteklemek için var.
CORS_ALLOW_ALL_ORIGINS = True

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

# Sadece django.contrib.admin'in kendi template'leri için gerekli - bu
# projede başka server-render edilen sayfa yok. APP_DIRS, ileride bir app'in
# kendi templates/'ine ihtiyacı olursa onu otomatik olarak buluyor.
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

# Artık aktif: django.contrib.auth kurulu olduğu için bu, Operator
# şifrelerini yönetiyor (admin login, createsuperuser, şifre sıfırlama).
# API'nin kendi kaynakları (cards/devices/employees) hâlâ kullanıcıya
# yönelik bir auth'a sahip değil - yukarıdaki REST_FRAMEWORK yorumuna bakın.
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
# Kaydedilen zaman damgaları UTC (spec 5.3); raporlar Django/Postgres
# session timezone'una güvenmek yerine REPORT_TZ ile açıkça çeviriyor.
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
