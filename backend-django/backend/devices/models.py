from django.db import models

from core.models import ExternallyManagedModel


class Device(ExternallyManagedModel):
    id = models.CharField(max_length=50, primary_key=True)
    ad = models.CharField(max_length=100, null=True, blank=True)
    kat = models.IntegerField(null=True, blank=True)
    son_gorulme = models.BigIntegerField(null=True, blank=True)
    durum = models.CharField(max_length=50, null=True, blank=True)
    fw = models.CharField(max_length=50, null=True, blank=True)
    queue_depth = models.IntegerField(null=True, blank=True)
    heap_free = models.IntegerField(null=True, blank=True)
    queue_overflow = models.IntegerField(null=True, blank=True)
    uptime_s = models.BigIntegerField(null=True, blank=True)
    ota_status = models.CharField(max_length=50, null=True, blank=True)
    ota_updated_at = models.BigIntegerField(null=True, blank=True)

    class Meta(ExternallyManagedModel.Meta):
        db_table = "devices"