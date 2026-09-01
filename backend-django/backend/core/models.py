from django.db import models


class Firmware(models.Model):
    version = models.CharField(max_length=50, primary_key=True)
    filename = models.CharField(max_length=255)
    md5 = models.CharField(max_length=32)
    size = models.IntegerField()
    uploaded_at = models.BigIntegerField(null=True, blank=True)

    class Meta:
        db_table = "firmware"
        managed = False


class AccessEvent(models.Model):
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

    class Meta:
        db_table = "access_events"
        managed = False
        constraints = [
            models.UniqueConstraint(fields=["device_id", "seq"], name="uniq_device_seq"),
        ]