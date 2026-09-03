from django.contrib.auth.models import AbstractUser
from django.db import models

from core.models import TimestampedModel


class Operator(AbstractUser, TimestampedModel):
    """The staff/operator identity for this system - the panel had no
    concept of a logged-in user at all before this. Built on Django's
    AbstractUser (battle-tested password hashing, the admin login form,
    is_staff/is_superuser for admin access) rather than a bespoke model,
    plus TimestampedModel for created_at/updated_at and a `role` field for
    the coarse admin-vs-operator distinction this panel actually needs.
    """
    ROLE_ADMIN = "admin"
    ROLE_OPERATOR = "operator"
    ROLE_CHOICES = [
        (ROLE_ADMIN, "Admin"),
        (ROLE_OPERATOR, "Operator"),
    ]

    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default=ROLE_OPERATOR)
    phone = models.CharField(max_length=30, null=True, blank=True)

    class Meta:
        db_table = "operators"

    def __str__(self):
        return self.get_full_name() or self.username


class AuditLog(TimestampedModel):
    """One row per meaningful mutation across the system - card/employee/
    device/firmware changes - answering "who did what, and when". Kept
    deliberately simple (a short action code + free-text target + a JSON
    details blob) rather than a full generic-relation setup, since this is
    for humans reading a history list, not for reconstructing exact
    before/after model state.

    `operator` is nullable: a request made before the frontend sends
    credentials, or a genuinely system-triggered action, has no operator to
    attribute it to - those show as "system" rather than being silently
    dropped or forced onto a fake user.
    """
    operator = models.ForeignKey(
        Operator, null=True, blank=True, on_delete=models.SET_NULL, related_name="audit_logs"
    )
    action = models.CharField(max_length=100)
    target_repr = models.CharField(max_length=255, blank=True)
    details = models.JSONField(null=True, blank=True)

    class Meta:
        db_table = "audit_logs"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["action"]),
            models.Index(fields=["created_at"]),
        ]

    def __str__(self):
        who = self.operator.username if self.operator else "system"
        return f"{who} {self.action} {self.target_repr}".strip()
