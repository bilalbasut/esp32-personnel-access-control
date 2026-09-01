from django.conf import settings
from django.urls import include, path
from django.views.static import serve as static_serve
from rest_framework.routers import DefaultRouter

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
    # All RESTful resources & custom actions:
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

    # Analytical / Reporting endpoint
    path("api/reports/pdks", PdksReportView.as_view(), name="reports-pdks"),

    # Direct static binary serving for ESP32 HTTP OTA download
    path(
        "firmware/<path:path>",
        static_serve,
        {"document_root": settings.FIRMWARE_DIR},
    ),
]