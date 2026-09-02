from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path('admin/', admin.site.urls),
    # Delegate routing to the isolated domain apps
    path('api/devices/', include('devices.urls')),
    path('api/access/', include('access.urls')),
]