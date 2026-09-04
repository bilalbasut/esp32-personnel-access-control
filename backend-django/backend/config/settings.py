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
    # rest_framework.authtoken (tek, süresi dolmayan opak token) JWT'ye
    # geçişle birlikte KALDIRILDI - bkz. SIMPLE_JWT ve aşağıdaki
    # DEFAULT_AUTHENTICATION_CLASSES. token_blacklist, logout'ta refresh
    # token'ı gerçekten geçersiz kılabilmek için gerekli (bkz. accounts/views.py
    # LogoutView) - kendi migration'larını getiriyor (OutstandingToken/
    # BlacklistedToken tabloları).
    "rest_framework_simplejwt.token_blacklist",
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
    # JWT (access + refresh, bkz. SIMPLE_JWT altta) artık ana auth yöntemi -
    # eski, süresi hiç dolmayan opak TokenAuthentication kaldırıldı.
    # SessionAuthentication sadece admin login'i ve DRF'in browsable
    # API'sindeki "Log in" linki için hâlâ duruyor, Vue frontend'i
    # ilgilendirmiyor.
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework_simplejwt.authentication.JWTAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ],
    # Artık zorunlu: önceden hiçbir endpoint login'in arkasına kilitli
    # değildi (frontend henüz kimlik bilgisi göndermiyordu, o yüzden bu
    # bilinçli olarak fiilen AllowAny bırakılmıştı). Login sayfası/JWT ile
    # birlikte geldi - artık login/refresh/logout dışındaki HER endpoint
    # kimlik doğrulaması istiyor (o üç view kendi permission_classes'ında
    # AllowAny ile açıkça override ediyor, bkz. accounts/views.py).
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
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

# Access token kısa ömürlü (15dk) ve stateless - süresi dolunca sunucu
# tarafında ayrıca "silinmesine" gerek yok, kendiliğinden geçersiz olur.
# Refresh token daha uzun ömürlü (7 gün) ama BLACKLIST_AFTER_ROTATION +
# ROTATE_REFRESH_TOKENS ile her /api/auth/refresh çağrısında eskisi
# geçersiz kılınıp yenisi veriliyor (bir refresh token'ın çalınıp süresiz
# tekrar tekrar kullanılabilmesini engelliyor) - logout'ta da aynı
# blacklist mekanizması kullanılıyor (bkz. accounts/views.py LogoutView):
# refresh token'ı elle blacklist'e ekleyip "artık kullanılamaz" hale
# getiriyor. Access token'ın kendisi logout'ta TERSİNE ÇEVRİLEMEZ (stateless,
# imzası hâlâ geçerli) - bu yüzden ömrü bilerek kısa tutuldu, en kötü
# ihtimalle logout sonrası 15 dakika daha geçerli kalabilir.
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
