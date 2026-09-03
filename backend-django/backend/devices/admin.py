from django.contrib import admin

from devices.models import Device


@admin.register(Device)
class DeviceAdmin(admin.ModelAdmin):
    list_display = ["id", "name", "location", "floor", "status", "last_seen_at", "fw"]
    search_fields = ["id", "name", "location"]
    list_filter = ["status", "floor"]
