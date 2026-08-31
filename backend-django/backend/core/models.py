from django.db import models


class Employee(models.Model):
    ad_soyad = models.CharField(max_length=255, null=True, blank=True)
    departman = models.CharField(max_length=100, null=True, blank=True)
    # Kept as SMALLINT (0/1) rather than BooleanField to match the original
    # schema's wire format and any existing data.
    aktif = models.SmallIntegerField(default=1)

    class Meta:
        db_table = "employees"


class Card(models.Model):
    uid = models.CharField(max_length=50, primary_key=True)
    employee = models.ForeignKey(
        Employee, null=True, blank=True, on_delete=models.SET_NULL,
        db_column="employee_id", related_name="cards",
    )
    floors = models.CharField(max_length=100, null=True, blank=True)
    valid_from = models.BigIntegerField(null=True, blank=True)
    valid_to = models.BigIntegerField(null=True, blank=True)
    win_start_m = models.SmallIntegerField(default=0)
    win_end_m = models.SmallIntegerField(default=1440)
    aktif = models.SmallIntegerField(default=1)

    class Meta:
        db_table = "cards"


class Device(models.Model):
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

    class Meta:
        db_table = "devices"


class AccessEvent(models.Model):
    # No FK constraint on device_id/employee_id in the original schema
    # either - events must never be rejected because a device or employee
    # row doesn't exist yet.
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
        constraints = [
            models.UniqueConstraint(fields=["device_id", "seq"], name="uniq_device_seq"),
        ]


class Firmware(models.Model):
    version = models.CharField(max_length=50, primary_key=True)
    filename = models.CharField(max_length=255)
    md5 = models.CharField(max_length=32)
    size = models.IntegerField()
    uploaded_at = models.BigIntegerField(null=True, blank=True)

    class Meta:
        db_table = "firmware"
