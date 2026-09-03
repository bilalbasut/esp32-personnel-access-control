from django.db import models

from core.models import TimestampedModel


class Device(TimestampedModel):
    id = models.CharField(max_length=50, primary_key=True)
    name = models.CharField(max_length=100, null=True, blank=True)
    floor = models.IntegerField(null=True, blank=True)
    # Unix epoch, written by the collector service on every heartbeat/
    # status/event - kept as a plain integer (not a DateTimeField) because
    # collector.py writes it via raw psycopg2, not through this model.
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
