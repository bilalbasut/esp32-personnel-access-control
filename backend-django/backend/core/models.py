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
    """Projedeki TÜM modeller için tek, ortak taban - daha önce üçe bölünmüş
    olan TimestampedModel/ActivatableModel/SoftDeletableModel burada
    birleşti (manager talebi: "1 basemodel, hepsi orada olsun"). Her satır
    artık created_at/updated_at/deleted_at/is_active TAŞIYOR - bilinçli
    olarak istisnasız: AccessEvent gibi doğası gereği "aktif/pasif"
    kavramına hiç ihtiyaç duymayan, sadece INSERT edilen bir donanım
    event-log'unda bile bu alanlar var ama hiçbir kod onları set etmeyecek -
    tutarlılık, her model için "en doğru" şemadan daha öncelikli tutuldu.

    created_at/updated_at, auto_now_add/auto_now YERİNE bilinçli olarak
    db_default (Postgres seviyesinde DEFAULT now()) kullanıyor: collector.py
    (MQTT event ingestion) ve seed script'i AccessEvent'e Django ORM'i hiç
    kullanmadan ham psycopg2 SQL'iyle INSERT atıyor - auto_now_add sadece
    ORM'in kendi save() yolunda çalışan bir Python-seviyesi varsayılan
    olduğundan, o satırlarda sessizce NULL bırakırdı. DB-seviyesi default,
    hangi yoldan yazılırsa yazılsın (ORM ya da ham SQL) doğru değeri
    garanti ediyor. updated_at'in ORM üzerinden yapılan her save()'de
    yenilenmesi ise aşağıdaki save() override'ıyla elle sağlanıyor (auto_now=True
    ile aynı semantik, ama db_default ile birlikte kullanılabilmesi için).

    `objects` (default manager) soft-delete edilmiş satırları her yerde
    dışarıda bırakır. `all_objects`, gerçekten her şeyi görmesi gereken
    yerler için (admin'in "silinenleri göster" view'ı, bir export, debug
    amaçlı sorgu) bilinçli olarak bırakılmış kaçış kapısı.

    `.delete()`'in kendisi soft-delete yapıyor - her çağıran yer (view'lar,
    admin toplu silme, ileride yazılacak bir management command, bir shell
    oturumu) sadece "doğru yazıldığı için" soft-delete davranışını "bedava"
    alsın diye. Gerçek, kalıcı bir DELETE FROM için (veri temizliği, bilinçli
    bir purge) `hard_delete()` kullanılmalı - bilerek daha "elle uzanılan",
    açık bir kaçış kapısı olarak bırakıldı.

    created_by/updated_by/deleted_by (Operator'e FK, nullable) "kim yaptı"
    sorusunu satırın kendi üzerinde, join'e gerek kalmadan cevaplıyor -
    view katmanı (bkz. core/audit_viewset.py) bunları set ediyor. Tam
    değişiklik geçmişi (hangi alan ne zamandan neye değişti) için bu üçü
    YETMEZ, sadece "şu an en son kim dokundu"yu tutar - geçmişin tamamı
    AuditLog'da (accounts/models.py) alan bazlı diff olarak tutuluyor.

    Aşağıdaki save()'de `update_fields` kısıtlaması varken bile updated_at
    her zaman kendini listeye ekliyor (bkz. save() override) - ama delete()
    içindeki save() hâlâ update_fields VERMİYOR: delete()'i override edip
    önce başka bir alanı da değiştiren bir alt sınıf (bkz. Card - silinen
    kart erişim vermeyi başka bir şeyin onu iptal etmesini beklemeden anında
    durdursun diye kendini de deaktive ediyor) o alanın da kalıcı olması
    için save()'in tam çalışmasına ihtiyaç duyuyor.
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
    """Donanımın bildirdiği her kapı-geçiş olayı için bir satır - bu Django
    uygulaması üzerinden değil, MQTT collector servisi (collector/
    collector.py) tarafından yazılıyor. Bilinçli olarak Device/Employee/
    Card'a gerçek bir FK DEĞİL: bu yüksek frekanslı bir donanım event
    log'u, bir cihaz/kart henüz kayıtlı/senkron değil diye insert'i
    reddetmek gerçek erişim olaylarının kaybolması demek olurdu. Bunun
    yerine ilişkilendirme okuma anında yapılıyor (aşağıdaki EventViewSet ve
    PdksReportView'daki LEFT JOIN'lere bakın). Index'ler de tam bu okuma
    anındaki join/filtrelerin kullandığı kolonlar üzerinde.

    BaseModel'den gelen is_active/deleted_at/created_by/updated_by/deleted_by
    bu satır için anlamsal olarak neredeyse hiç kullanılmayacak - bu tablo
    donanımın bildirdiği, hiç güncellenmeyen, sadece INSERT edilen bir
    event log'u, "aktif/pasif" ya da "kim sildi" kavramına doğası gereği
    ihtiyacı yok. Yine de bilinçli olarak istisna tutulmadı (bkz. BaseModel
    docstring'i) - tutarlılık için burada duruyorlar, kullanılmayacak
    olsalar da."""
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
