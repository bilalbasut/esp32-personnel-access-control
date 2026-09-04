from django.conf import settings
from django.db import models
from django.db.models.functions import Now
from django.utils import timezone


class ActiveManager(models.Manager):
    """BaseModel'in default manager'ı: soft-delete edilmiş satırları her
    normal queryset'ten (list/detail view'lar, FK gezinmesi, admin liste
    sayfaları) hiç kimsenin ayrıca filtrelemeyi hatırlamasına gerek kalmadan
    gizler."""
    def get_queryset(self):
        return super().get_queryset().filter(deleted_at__isnull=True)


class BaseModel(models.Model):
    """Projedeki tüm modeller için tek, ortak taban. Her satır
    artık created_at/updated_at/deleted_at/is_active taşıyor.
    """
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
        # auto_now=True'nun elle yapılan hali - db_default ile bir arada
        # kullanılamadığı için (bkz. sınıf docstring'i). Django'nun kendi
        # auto_now'ıyla aynı sınırlamayı bilerek koruyor: update_fields
        # verilip updated_at listede değilse, bu satır DB'ye YAZILMAZ - bu
        # bir bug değil, çağıranın "sadece şu alanları değiştir" niyetine
        # saygı; delete()'in kendisi zaten hiç update_fields vermiyor.
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
        """delete() için açık bir alias - davranış aynı, sadece çağıran yer
        ".delete()" yerine "soft delete" demek istediğinde kullanılıyor."""
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
    # TimestampedModel'in auto_now_add'ı yerine bilinçli olarak elle set
    # edilen bir upload zaman damgası (unix epoch, FirmwareViewSet.
    # upload_binary tarafından set ediliyor) - tek bir yetkili "ne zaman"
    # alanı, birbiriyle çelişebilecek iki zaman damgasını önlüyor.
    uploaded_at = models.BigIntegerField(null=True, blank=True)

    class Meta:
        db_table = "firmware"


class AccessEvent(BaseModel):
    
    device_id = models.CharField(max_length=50, null=True, blank=True, db_index=True)
    seq = models.IntegerField(null=True, blank=True)
    uid = models.CharField(max_length=50, null=True, blank=True)
    employee_id = models.IntegerField(null=True, blank=True, db_index=True)
    ts_utc = models.BigIntegerField(null=True, blank=True, db_index=True)
    ts_source = models.SmallIntegerField(null=True, blank=True)
    dir = models.SmallIntegerField(null=True, blank=True)
    result = models.SmallIntegerField(null=True, blank=True)
    mode = models.SmallIntegerField(null=True, blank=True)
    # collector'ın bu satırı gerçekten yazdığı an (unix epoch) - event'in
    # kendi donanım-raporlu zamanı olan ts_utc'den farklı.
    ingested_at = models.BigIntegerField(null=True, blank=True)
    # Güvenlik ağı: bu satırın parse edildiği ham MQTT JSON payload'ı.
    # Kolon-eşleme hataları ya da henüz bağlanmamış yeni bir firmware alanı
    # olmasaydı bu veriyi kalıcı olarak kaybederdi - bu sayede ileride
    # replay/backfill yapılabiliyor. Nullable, çünkü mevcut satırlar (ve ham
    # payload'ı elinde olmayan hiçbir insert yolu) bundan etkilenmesin.
    raw_payload = models.JSONField(null=True, blank=True)

    class Meta:
        db_table = "access_events"
        constraints = [
            models.UniqueConstraint(fields=["device_id", "seq"], name="uniq_device_seq"),
        ]
