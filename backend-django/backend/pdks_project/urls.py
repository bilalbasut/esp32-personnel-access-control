from django.conf import settings
from django.urls import include, path
from django.views.static import serve as static_serve

urlpatterns = [
    path("api/", include("core.urls")),
    # Equivalent of app.use('/firmware', express.static(FIRMWARE_DIR)) in
    # server.js - lets the ESP32 download the .bin directly by URL.
    path(
        "firmware/<path:path>",
        static_serve,
        {"document_root": settings.FIRMWARE_DIR},
    ),
]
