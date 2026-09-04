from django.conf import settings
from django.contrib import admin
from django.urls import include, path
from django.views.static import serve as static_serve
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from accounts.views import LogoutView, MeView
from devices.views import DeviceViewSet
from cards.views import CardViewSet, EmployeeViewSet
from core.views import EventViewSet, FirmwareViewSet, PdksReportView

router = DefaultRouter(trailing_slash=False)
router.register(r"devices", DeviceViewSet, basename="device")
router.register(r"cards", CardViewSet, basename="card")
router.register(r"employees", EmployeeViewSet, basename="employee")
router.register(r"events", EventViewSet, basename="event")
router.register(r"firmware", FirmwareViewSet, basename="firmware")

urlpatterns = [
    # Tüm RESTful kaynaklar & custom action'lar:
    # - /api/devices (list/create)
    # - /api/devices/<id> (retrieve/update/delete)
    # - /api/devices/<id>/command (@action)
    # - /api/devices/<id>/ota (@action)
    # - /api/cards (list/create)
    # - /api/cards/<uid> (retrieve/update/delete)
    # - /api/cards/add (@action)
    # - /api/cards/revoke (@action)
    # - /api/cards/<uid>/assign (@action)
    # - /api/employees (list/create/retrieve/update)
    # - /api/events (list)
    # - /api/firmware (list)
    # - /api/firmware/upload (@action)
    path("api/", include(router.urls)),

    # Analitik / Raporlama endpoint'i
    path("api/reports/pdks", PdksReportView.as_view(), name="reports-pdks"),

    # Operatör auth (JWT): POST {username, password} -> {"access", "refresh"}
    # (simplejwt'nin hazır view'ı - custom login kodu gerekmiyor). Sonraki
    # isteklerde access token'ı `Authorization: Bearer <access>` olarak geri
    # gönder; access süresi dolunca (15dk, bkz. config/settings.py SIMPLE_JWT)
    # refresh token'ı /api/auth/refresh'e verip yenisini al. /api/auth/logout
    # refresh token'ı blacklist'e ekler.
    path("api/auth/login", TokenObtainPairView.as_view(), name="auth-login"),
    path("api/auth/refresh", TokenRefreshView.as_view(), name="auth-refresh"),
    path("api/auth/logout", LogoutView.as_view(), name="auth-logout"),
    path("api/auth/me", MeView.as_view(), name="auth-me"),

    # Django admin - Vue frontend'inden bağımsız, operatörler/kartlar/
    # employee'ler/cihazlar/firmware için bugün itibarıyla çalışan bir
    # yönetim arayüzü.
    path("admin/", admin.site.urls),

    # ESP32'nin HTTP OTA indirmesi için doğrudan static binary servisi
    path(
        "firmware/<path:path>",
        static_serve,
        {"document_root": settings.FIRMWARE_DIR},
    ),
]