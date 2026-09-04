"""Bir şeyi değiştiren her view'ın AuditLog satırını elle kurmak yerine aynı
fonksiyonu aynı şekilde çağırması için küçük bir yardımcı."""
from accounts.models import AuditLog


def log_action(request, action, target_repr="", details=None):
    """Mevcut request için bir "kim ne yaptı" kaydı oluşturur.

    Request kimliklenmemişse `operator` None ("system" olarak gösterilir) -
    ki bu rollout itibarıyla frontend token göndermeye başlayana kadar HER
    request için geçerli. Bu bir bug değil, beklenen durum: operatörler
    giriş yapmaya başladığı an audit kapsamı backend'de hiçbir ek değişiklik
    gerekmeden kendiliğinden iyileşiyor.
    """
    user = getattr(request, "user", None)
    operator = user if user is not None and getattr(user, "is_authenticated", False) else None
    AuditLog.objects.create(
        operator=operator,
        action=action,
        target_repr=target_repr,
        details=details or {},
    )
