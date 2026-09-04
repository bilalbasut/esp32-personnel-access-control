from django.db import models

from core.models import BaseModel


class Device(BaseModel):
    id = models.CharField(max_length=50, primary_key=True)
    name = models.CharField(max_length=100, null=True, blank=True)
    floor = models.IntegerField(null=True, blank=True)
    # Elle girilen kurulum metadata'sı (oda/koridor adı, bakım için statik
    # ağ bilgisi) - donanım/MQTT protokolü tarafından raporlanmıyor, yani
    # bunlar otomatik senkronize edilmek yerine bir operatörün API/admin
    # üzerinden ne girdiyse öyle kalıyor.
    location = models.CharField(max_length=255, null=True, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    mac_address = models.CharField(max_length=17, null=True, blank=True)
    # Unix epoch, collector servisi tarafından her heartbeat/status/event'te
    # yazılıyor - düz bir integer olarak tutuluyor (DateTimeField değil),
    # çünkü collector.py bunu bu model üzerinden değil, ham psycopg2 ile yazıyor.
    last_seen_at = models.BigIntegerField(null=True, blank=True)
    status = models.CharField(max_length=50, null=True, blank=True)
    fw = models.CharField(max_length=50, null=True, blank=True)
    queue_depth = models.IntegerField(null=True, blank=True)
    heap_free = models.IntegerField(null=True, blank=True)
    queue_overflow = models.IntegerField(null=True, blank=True)
    uptime_s = models.BigIntegerField(null=True, blank=True)
    ota_status = models.CharField(max_length=50, null=True, blank=True)
    ota_updated_at = models.BigIntegerField(null=True, blank=True)

    class Meta:
        db_table = "devices"

    def __str__(self):
        # AuditLog'daki target_repr için (core/audit_viewset.py) - eski
        # elle yazılan log_action() çağrılarındaki f"Device {id} ({name})"
        # formatıyla aynı okunabilirliği koruyor.
        return f"{self.id} ({self.name})" if self.name else self.id
