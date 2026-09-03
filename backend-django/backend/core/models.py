from django.db import models
from django.utils import timezone


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


class ActiveManager(models.Manager):
    """Default manager for SoftDeletableModel: hides soft-deleted rows from
    every normal queryset (list/detail views, FK traversal, admin list
    pages) without anyone needing to remember to filter for it."""
    def get_queryset(self):
        return super().get_queryset().filter(deleted_at__isnull=True)


class SoftDeletableModel(models.Model):
    """Base for models where "delete" should preserve history instead of
    erasing it (Employee, Card). AccessEvent/AuditLog rows referencing a
    since-removed card or employee stay explainable instead of pointing at
    nothing - this is the direct fix for that gap.

    `objects` (the default manager) excludes soft-deleted rows everywhere.
    `all_objects` is the explicit escape hatch for anything that genuinely
    needs to see everything - an admin "show removed" view, an export, a
    debugging query.

    `.delete()` itself soft-deletes - this is what closes the gap that used
    to exist here: every call site (views, admin bulk-delete, a future
    management command, a shell session) got soft-delete behavior "for
    free" purely by being written correctly, with nothing stopping a real
    DELETE FROM if one of them forgot. Now the model enforces it. Use
    `hard_delete()` for an actual, permanent DELETE FROM (data cleanup, a
    deliberate purge) - it's the explicit, harder-to-reach-for escape hatch,
    on purpose.

    No `update_fields` restriction on the save() below: a subclass that
    overrides delete() to also flip another field first (see Card, which
    deactivates itself so a deleted card stops granting access immediately
    instead of waiting for something else to revoke it) needs the full
    save() to persist that field too, not just deleted_at.
    """
    deleted_at = models.DateTimeField(null=True, blank=True)

    objects = ActiveManager()
    all_objects = models.Manager()

    class Meta:
        abstract = True

    def delete(self, *args, **kwargs):
        self.deleted_at = timezone.now()
        self.save()

    def hard_delete(self, *args, **kwargs):
        super().delete(*args, **kwargs)

    def soft_delete(self):
        """Explicit alias for delete() - same behavior, for call sites that
        want to say "soft delete" out loud rather than just ".delete()"."""
        self.delete()

    def restore(self):
        self.deleted_at = None
        self.save()

    @property
    def is_deleted(self):
        return self.deleted_at is not None


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
    # Safety net: the exact MQTT JSON payload this row was parsed from.
    # Column-mapping bugs or a firmware update that adds a new field you
    # haven't wired up yet would otherwise lose that data permanently -
    # this lets you replay/backfill later instead. Nullable so existing
    # rows (and any insert path that doesn't have the raw payload handy)
    # aren't affected.
    raw_payload = models.JSONField(null=True, blank=True)

    class Meta:
        db_table = "access_events"
        constraints = [
            models.UniqueConstraint(fields=["device_id", "seq"], name="uniq_device_seq"),
        ]
