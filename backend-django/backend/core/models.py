from django.db import models


class TimestampedModel(models.Model):
    """Base for models that should track row creation/update times.
    `created_at` is set once on insert; `updated_at` refreshes on every
    save(). Skip this base for append-only/event-log tables where rows are
    never updated after insert (see AccessEvent, which tracks its own
    hardware/ingestion timestamps instead)."""
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class ActivatableModel(models.Model):
    """Base for models with a simple active/inactive toggle instead of
    hard-deleting rows (Employee, Card)."""
    is_active = models.BooleanField(default=True)

    class Meta:
        abstract = True


class Firmware(models.Model):
    version = models.CharField(max_length=50, primary_key=True)
    filename = models.CharField(max_length=255)
    md5 = models.CharField(max_length=32)
    size = models.IntegerField()
    # Explicit upload bookkeeping timestamp (unix epoch, set by
    # FirmwareViewSet.upload_binary) rather than TimestampedModel's
    # auto_now_add - keeping one authoritative "when" field here avoids two
    # timestamps that could disagree.
    uploaded_at = models.BigIntegerField(null=True, blank=True)

    class Meta:
        db_table = "firmware"


class AccessEvent(models.Model):
    """One row per door-access event reported by hardware, written by the
    MQTT collector service (collector/collector.py), not through this
    Django app. Deliberately NOT a real FK to Device/Employee/Card: this is
    a high-frequency hardware event log, and rejecting an insert just
    because a device or card hasn't been registered/synced yet would mean
    losing real access events. Resolved at read time instead (see the
    LEFT JOINs in EventViewSet and PdksReportView below). Indexed on the
    columns those read-time joins/filters actually use."""
    device_id = models.CharField(max_length=50, null=True, blank=True, db_index=True)
    seq = models.IntegerField(null=True, blank=True)
    uid = models.CharField(max_length=50, null=True, blank=True)
    employee_id = models.IntegerField(null=True, blank=True, db_index=True)
    ts_utc = models.BigIntegerField(null=True, blank=True, db_index=True)
    ts_source = models.SmallIntegerField(null=True, blank=True)
    dir = models.SmallIntegerField(null=True, blank=True)
    result = models.SmallIntegerField(null=True, blank=True)
    mode = models.SmallIntegerField(null=True, blank=True)
    # When the collector actually wrote this row (unix epoch) - distinct
    # from ts_utc, which is the event's own hardware-reported time.
    ingested_at = models.BigIntegerField(null=True, blank=True)

    class Meta:
        db_table = "access_events"
        constraints = [
            models.UniqueConstraint(fields=["device_id", "seq"], name="uniq_device_seq"),
        ]
