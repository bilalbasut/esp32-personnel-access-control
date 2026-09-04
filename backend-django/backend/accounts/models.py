from django.contrib.auth.models import AbstractUser, UserManager
from django.db import models

from core.models import BaseModel


class OperatorManager(UserManager):
    """UserManager.create_user() + ActiveManager'ın soft-delete filtresi tek manager'da.
    AbstractUser ve BaseModel ikisi de "objects" tanımlıyor - Django alan çakışmasını
    hataya çevirir ama manager çakışmasını sessizce üst üste yazar, kazanan belirsiz kalır."""
    def get_queryset(self):
        return super().get_queryset().filter(deleted_at__isnull=True)


class Operator(AbstractUser, BaseModel):
    """Panelin kullanıcı kimliği, AbstractUser + BaseModel. is_active burada bilerek
    yeniden tanımlı: ikisi de aynı adda alan tanımlar, Django bunu clash sayıp patlar -
    tesadüfen faydalı da: deactivate = hem pasif görünür hem giriş yapamaz, tek bayrak."""
    ROLE_ADMIN = "admin"
    ROLE_OPERATOR = "operator"
    ROLE_CHOICES = [
        (ROLE_ADMIN, "Admin"),
        (ROLE_OPERATOR, "Operator"),
    ]

    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default=ROLE_OPERATOR)
    phone = models.CharField(max_length=30, null=True, blank=True)
    is_active = models.BooleanField(default=True, db_default=True)

    objects = OperatorManager()

    class Meta:
        db_table = "operators"

    def __str__(self):
        return self.get_full_name() or self.username


class AuditLog(BaseModel):
    """"Kim ne zaman ne yaptı" satırı - AuditedModelViewSet CRUD'da otomatik yazar,
    CRUD-dışı @action'lar log_action()'ı elle çağırır. `operator` nullable: sistem
    tetikli aksiyonlar "system" gösterilir. created_by, operator ile aynı değeri taşır
    (log_action() ikisini de set eder) - BaseModel'i istisnasız uygulamanın fazlalığı."""
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
