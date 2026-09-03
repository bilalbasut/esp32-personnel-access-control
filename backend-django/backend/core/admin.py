from django.contrib import admin

from core.models import Firmware, AccessEvent


@admin.register(Firmware)
class FirmwareAdmin(admin.ModelAdmin):
    list_display = ["version", "filename", "size", "uploaded_at"]
    search_fields = ["version", "filename"]


@admin.register(AccessEvent)
class AccessEventAdmin(admin.ModelAdmin):
    """Read-only - these rows are written by the MQTT collector, not by
    anything a person should be editing by hand."""
    list_display = ["id", "device_id", "uid", "employee_id", "ts_utc", "dir", "result"]
    list_filter = ["result", "dir", "device_id"]
    search_fields = ["uid", "device_id"]
    readonly_fields = [f.name for f in AccessEvent._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
