from django.db import models


class ExternallyManagedModel(models.Model):
    """Base for models whose tables are owned by core's original migration
    (0001_initial, plus core/migrations/0002 for the ones that later moved
    app) rather than by Django's normal makemigrations/migrate lifecycle.

    Every concrete subclass must still declare its own `class Meta` for
    `db_table` — subclass `ExternallyManagedModel.Meta` (not `models.Model`)
    so `managed = False` carries over instead of silently resetting to the
    Django default of True:

        class Foo(ExternallyManagedModel):
            class Meta(ExternallyManagedModel.Meta):
                db_table = "foo"
    """
    class Meta:
        abstract = True
        managed = False


class Firmware(ExternallyManagedModel):
    version = models.CharField(max_length=50, primary_key=True)
    filename = models.CharField(max_length=255)
    md5 = models.CharField(max_length=32)
    size = models.IntegerField()
    uploaded_at = models.BigIntegerField(null=True, blank=True)

    class Meta(ExternallyManagedModel.Meta):
        db_table = "firmware"


class AccessEvent(ExternallyManagedModel):
    device_id = models.CharField(max_length=50, null=True, blank=True)
    seq = models.IntegerField(null=True, blank=True)
    uid = models.CharField(max_length=50, null=True, blank=True)
    employee_id = models.IntegerField(null=True, blank=True)
    ts_utc = models.BigIntegerField(null=True, blank=True)
    ts_source = models.SmallIntegerField(null=True, blank=True)
    dir = models.SmallIntegerField(null=True, blank=True)
    result = models.SmallIntegerField(null=True, blank=True)
    mode = models.SmallIntegerField(null=True, blank=True)
    alindi_at = models.BigIntegerField(null=True, blank=True)

    class Meta(ExternallyManagedModel.Meta):
        db_table = "access_events"
        constraints = [
            models.UniqueConstraint(fields=["device_id", "seq"], name="uniq_device_seq"),
        ]