from django.db import models

from core.models import BaseModel


class Device(BaseModel):
    id = models.CharField(max_length=50, primary_key=True)
    name = models.CharField(max_length=100, null=True, blank=True)
    floor = models.IntegerField(null=True, blank=True)
    location = models.CharField(max_length=255, null=True, blank=True)  # elle girilir, MQTT'den gelmez
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    mac_address = models.CharField(max_length=17, null=True, blank=True)
    last_seen_at = models.BigIntegerField(null=True, blank=True)  # düz integer: collector ham SQL'le yazıyor, ORM değil
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
        return f"{self.id} ({self.name})" if self.name else self.id
