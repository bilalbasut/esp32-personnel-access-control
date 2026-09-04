from django.contrib.auth.models import AbstractUser
from django.db import models

from core.models import TimestampedModel


class Operator(AbstractUser, TimestampedModel):
    """Panelin operatör/kullanıcı kimliği - daha önce sistemde giriş yapmış
    kullanıcı kavramı yoktu. Sıfırdan model yazmak yerine Django'nun
    AbstractUser'ı üzerine kuruldu (hazır ve test edilmiş şifre hash'leme,
    admin login formu, is_staff/is_superuser); TimestampedModel'den
    created_at/updated_at, `role` alanından da bu panelin ihtiyaç duyduğu
    kabaca admin/operator ayrımı geliyor.
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
    """Sistemdeki her anlamlı değişiklik (kart/employee/device/firmware) için
    bir satır - "kim, ne zaman, ne yaptı" sorusuna cevap veriyor. Bilinçli
    olarak basit tutuldu (kısa bir action kodu + serbest metin target +
    JSON details) - tam bir generic-relation altyapısı yerine, çünkü bu bir
    geçmiş listesini okuyan insan için, model öncesi/sonrası tam state'i
    geri kurmak için değil.

    `operator` nullable: frontend henüz kimlik bilgisi göndermeden yapılan
    bir istek, ya da gerçekten sistem tetikli bir aksiyon, hiçbir operatöre
    atfedilemez - bunlar sessizce düşürülmek ya da sahte bir kullanıcıya
    bağlanmak yerine "system" olarak gösteriliyor.
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
