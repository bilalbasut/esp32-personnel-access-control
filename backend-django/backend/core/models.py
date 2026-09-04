from django.conf import settings
from django.db import models
from django.db.models.functions import Now
from django.utils import timezone


class ActiveManager(models.Manager):
    """Default manager - soft-delete edilmiş satırları her queryset'ten gizler."""
    def get_queryset(self):
        return super().get_queryset().filter(deleted_at__isnull=True)


class BaseModel(models.Model):
    """Tüm modellerin ortak tabanı. db_default (Postgres DEFAULT now()) kullanır,
    auto_now_add değil - collector.py/seed script ORM'i bypass edip ham SQL INSERT
    atıyor, auto_now_add o yolda sessizce NULL bırakırdı. `all_objects` soft-delete
    filtresiz kaçış kapısı; gerçek DELETE için `hard_delete()`."""
    created_at = models.DateTimeField(db_default=Now())
    updated_at = models.DateTimeField(db_default=Now())
    deleted_at = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True, db_default=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+"
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+"
    )
    deleted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+"
    )

    objects = ActiveManager()
    all_objects = models.Manager()

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        # auto_now=True'nun elle hali (db_default ile birlikte kullanılamıyor) - update_fields'a updated_at'i zorla ekler.
        self.updated_at = timezone.now()
        update_fields = kwargs.get("update_fields")
        if update_fields is not None:
            kwargs["update_fields"] = {*update_fields, "updated_at"}
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        self.deleted_at = timezone.now()
        self.save()

    def hard_delete(self, *args, **kwargs):
        super().delete(*args, **kwargs)

    def soft_delete(self):
        """delete()'in okunabilir alias'ı."""
        self.delete()

    def restore(self):
        self.deleted_at = None
        self.save()

    @property
    def is_deleted(self):
        return self.deleted_at is not None


class Firmware(BaseModel):
    version = models.CharField(max_length=50, primary_key=True)
    filename = models.CharField(max_length=255)
    md5 = models.CharField(max_length=32)
    size = models.IntegerField()
    uploaded_at = models.BigIntegerField(null=True, blank=True)  # elle set edilir (FirmwareViewSet.upload_binary), auto değil

    class Meta:
        db_table = "firmware"


class AccessEvent(BaseModel):
    """MQTT collector'ın yazdığı ham kapı-geçiş log'u. Device/Employee/Card'a gerçek FK
    yok, kayıt henüz senkron olmayan bir cihazdan reddedilmesin diye - ilişkilendirme
    okuma anında LEFT JOIN ile yapılır (EventViewSet, PdksReportView)."""
    device_id = models.CharField(max_length=50, null=True, blank=True, db_index=True)
    seq = models.IntegerField(null=True, blank=True)
    uid = models.CharField(max_length=50, null=True, blank=True)
    employee_id = models.IntegerField(null=True, blank=True, db_index=True)
    ts_utc = models.BigIntegerField(null=True, blank=True, db_index=True)
    ts_source = models.SmallIntegerField(null=True, blank=True)
    dir = models.SmallIntegerField(null=True, blank=True)
    result = models.SmallIntegerField(null=True, blank=True)
    mode = models.SmallIntegerField(null=True, blank=True)
    ingested_at = models.BigIntegerField(null=True, blank=True)  # collector'ın yazdığı an, ts_utc'den farklı
    raw_payload = models.JSONField(null=True, blank=True)  # ham MQTT payload'ı, replay/backfill için

    class Meta:
        db_table = "access_events"
        constraints = [
            models.UniqueConstraint(fields=["device_id", "seq"], name="uniq_device_seq"),
        ]
