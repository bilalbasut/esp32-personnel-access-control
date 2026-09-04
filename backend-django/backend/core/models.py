from django.db import models
from django.utils import timezone


class TimestampedModel(models.Model):
    """Satırın oluşturulma/güncellenme zamanını tutması gereken modeller
    için taban sınıf. `created_at` insert'te bir kere set edilir;
    `updated_at` her save()'de yenilenir. Insert'ten sonra hiç güncellenmeyen
    append-only/event-log tablolarında bu taban kullanılmıyor (bkz.
    AccessEvent - o kendi donanım/ingestion zaman damgalarını kullanıyor)."""
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class ActivatableModel(models.Model):
    """Satırları hard-delete etmek yerine basit bir aktif/pasif anahtarına
    ihtiyaç duyan modeller için taban (Employee, Card)."""
    is_active = models.BooleanField(default=True)

    class Meta:
        abstract = True


class ActiveManager(models.Manager):
    """SoftDeletableModel'in default manager'ı: soft-delete edilmiş satırları
    her normal queryset'ten (list/detail view'lar, FK gezinmesi, admin liste
    sayfaları) hiç kimsenin ayrıca filtrelemeyi hatırlamasına gerek kalmadan
    gizler."""
    def get_queryset(self):
        return super().get_queryset().filter(deleted_at__isnull=True)


class SoftDeletableModel(models.Model):
    """"Silme"nin geçmişi yok etmek yerine korumasını istediğimiz modeller
    için taban (Employee, Card). Silinmiş bir karta/employee'ye referans
    veren AccessEvent/AuditLog satırları hiçliğe işaret etmek yerine hâlâ
    anlamlı kalıyor - bu sınıf tam olarak o boşluğu kapatıyor.

    `objects` (default manager) soft-delete edilmiş satırları her yerde
    dışarıda bırakır. `all_objects`, gerçekten her şeyi görmesi gereken
    yerler için (admin'in "silinenleri göster" view'ı, bir export, debug
    amaçlı sorgu) bilinçli olarak bırakılmış kaçış kapısı.

    `.delete()`'in kendisi soft-delete yapıyor - burada kapatılan asıl açık
    buydu: her çağıran yer (view'lar, admin toplu silme, ileride yazılacak
    bir management command, bir shell oturumu) sadece "doğru yazıldığı
    için" soft-delete davranışını "bedava" alıyordu; biri unutursa gerçek
    bir DELETE FROM'u hiçbir şey engellemiyordu. Artık bunu model
    zorluyor. Gerçek, kalıcı bir DELETE FROM için (veri temizliği, bilinçli
    bir purge) `hard_delete()` kullanılmalı - bilerek daha "elle uzanılan",
    açık bir kaçış kapısı olarak bırakıldı.

    Aşağıdaki save()'de `update_fields` kısıtlaması YOK: delete()'i
    override edip önce başka bir alanı da değiştiren bir alt sınıf (bkz.
    Card - silinen kart erişim vermeyi başka bir şeyin onu iptal etmesini
    beklemeden anında durdursun diye kendini de deaktive ediyor) o alanın da
    kalıcı olması için save()'in tam çalışmasına ihtiyaç duyuyor, sadece
    deleted_at'in değil.
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
        """delete() için açık bir alias - davranış aynı, sadece çağıran yer
        ".delete()" yerine "soft delete" demek istediğinde kullanılıyor."""
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
    # TimestampedModel'in auto_now_add'ı yerine bilinçli olarak elle set
    # edilen bir upload zaman damgası (unix epoch, FirmwareViewSet.
    # upload_binary tarafından set ediliyor) - tek bir yetkili "ne zaman"
    # alanı, birbiriyle çelişebilecek iki zaman damgasını önlüyor.
    uploaded_at = models.BigIntegerField(null=True, blank=True)

    class Meta:
        db_table = "firmware"


class AccessEvent(models.Model):
    """Donanımın bildirdiği her kapı-geçiş olayı için bir satır - bu Django
    uygulaması üzerinden değil, MQTT collector servisi (collector/
    collector.py) tarafından yazılıyor. Bilinçli olarak Device/Employee/
    Card'a gerçek bir FK DEĞİL: bu yüksek frekanslı bir donanım event
    log'u, bir cihaz/kart henüz kayıtlı/senkron değil diye insert'i
    reddetmek gerçek erişim olaylarının kaybolması demek olurdu. Bunun
    yerine ilişkilendirme okuma anında yapılıyor (aşağıdaki EventViewSet ve
    PdksReportView'daki LEFT JOIN'lere bakın). Index'ler de tam bu okuma
    anındaki join/filtrelerin kullandığı kolonlar üzerinde."""
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
