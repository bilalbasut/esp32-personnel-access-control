"""Bir şeyi değiştiren her view'ın AuditLog satırını elle kurmak yerine aynı
fonksiyonu aynı şekilde çağırması için küçük bir yardımcı."""
from accounts.models import AuditLog


def log_action(request, action, target_repr="", details=None):
    """Mevcut request için "kim ne yaptı" kaydı oluşturur. Kimliklenmemişse operator=None ("system")."""
    user = getattr(request, "user", None)
    operator = user if user is not None and getattr(user, "is_authenticated", False) else None
    AuditLog.objects.create(
        operator=operator,
        action=action,
        target_repr=target_repr,
        details=details or {},
        created_by=operator,  # ham ORM çağrısı, AuditedModelViewSet'in dışında - elle set edilmezse hep None kalır
    )
