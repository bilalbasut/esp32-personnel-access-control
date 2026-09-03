from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from accounts.models import Operator, AuditLog


@admin.register(Operator)
class OperatorAdmin(UserAdmin):
    """Extends Django's stock UserAdmin (battle-tested password-change
    flow, permissions UI) rather than a hand-rolled one - just adds the
    fields this project's Operator has beyond AbstractUser."""
    fieldsets = UserAdmin.fieldsets + (
        ("PDKS role", {"fields": ("role", "phone")}),
    )
    list_display = ["username", "email", "role", "is_staff", "is_active"]
    list_filter = UserAdmin.list_filter + ("role",)


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    """Read-only by design - an audit trail that could be edited or
    deleted through the same UI it's meant to hold accountable isn't much
    of an audit trail."""
    list_display = ["created_at", "operator", "action", "target_repr"]
    list_filter = ["action"]
    search_fields = ["target_repr", "operator__username"]
    readonly_fields = [f.name for f in AuditLog._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser
