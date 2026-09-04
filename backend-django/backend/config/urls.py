from django.conf import settings
from django.contrib import admin
from django.urls import include, path
from django.views.static import serve as static_serve
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from accounts.views import LogoutView, MeView, OperatorViewSet
from devices.views import DeviceViewSet
from cards.views import CardViewSet, EmployeeViewSet
from core.views import EventViewSet, FirmwareViewSet, PdksReportView

router = DefaultRouter(trailing_slash=False)
router.register(r"devices", DeviceViewSet, basename="device")
router.register(r"cards", CardViewSet, basename="card")
router.register(r"employees", EmployeeViewSet, basename="employee")
router.register(r"events", EventViewSet, basename="event")
router.register(r"firmware", FirmwareViewSet, basename="firmware")
router.register(r"operators", OperatorViewSet, basename="operator")  # admin-only, bkz. accounts/permissions.py

urlpatterns = [
    path("api/", include(router.urls)),  # + @action sub-routes: command/ota, add/revoke/assign, upload
    path("api/reports/pdks", PdksReportView.as_view(), name="reports-pdks"),

    # simplejwt'nin hazır view'ları - custom login kodu yok.
    path("api/auth/login", TokenObtainPairView.as_view(), name="auth-login"),
    path("api/auth/refresh", TokenRefreshView.as_view(), name="auth-refresh"),
    path("api/auth/logout", LogoutView.as_view(), name="auth-logout"),
    path("api/auth/me", MeView.as_view(), name="auth-me"),

    path("admin/", admin.site.urls),

    # ESP32'nin HTTP OTA indirmesi için doğrudan static binary servisi
    path(
        "firmware/<path:path>",
        static_serve,
        {"document_root": settings.FIRMWARE_DIR},
    ),
]