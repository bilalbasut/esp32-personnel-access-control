from django.contrib.auth.models import AbstractUser, UserManager
from django.db import models

from core.models import BaseModel


class OperatorManager(UserManager):
    """UserManager'ın create_user()/create_superuser()'ı (Django'nun kendi
    createsuperuser komutu VE accounts/tests.py bunlara ihtiyaç duyuyor) ile
    BaseModel.ActiveManager'ın soft-delete filtresini TEK manager'da
    birleştiriyor.

    NEDEN GEREKLİ: is_active'teki gibi BURADA DA iki abstract base
    (AbstractUser, BaseModel) aynı isimde ("objects") bir manager
    tanımlıyor - ama is_active'in aksine Django ALAN çakışmasını (clash)
    açıkça hataya çeviriyor, MANAGER çakışmasını değil: iki abstract base
    "objects" tanımladığında Django sessizce üst üste yazıyor, kazanan
    Django'nun bases sırasını işleme DETAYINA bağlı - yani redeclare
    etmezsek `Operator.objects`'in gerçekten UserManager mi yoksa
    ActiveManager mi olacağı belirsiz/kırılgan bir varsayım olurdu (ve
    yanlış çıkarsa create_user() burada hiç yok sayılırdı). is_active'teki
    aynı prensip: açık, örtük olandan iyidir - concrete sınıf (Operator)
    hangi manager'ı istediğini kendi açıkça söylüyor.
    """
    def get_queryset(self):
        return super().get_queryset().filter(deleted_at__isnull=True)


class Operator(AbstractUser, BaseModel):
    """Panelin operatör/kullanıcı kimliği - daha önce sistemde giriş yapmış
    kullanıcı kavramı yoktu. Sıfırdan model yazmak yerine Django'nun
    AbstractUser'ı üzerine kuruldu (hazır ve test edilmiş şifre hash'leme,
    admin login formu, is_staff/is_superuser); BaseModel'den created_at/
    updated_at/deleted_at/created_by/updated_by/deleted_by geliyor, `role`
    alanından da bu panelin ihtiyaç duyduğu kabaca admin/operator ayrımı.

    is_active AŞAĞIDA BİLEREK YENİDEN TANIMLANDI: hem AbstractUser hem
    BaseModel kendi is_active alanını tanımlıyor - iki abstract base aynı
    isimde alan tanımlayınca Django bunu clash sayıp patlıyor, TEK çözüm
    concrete sınıfın (Operator) o alanı açıkça override etmesi. Bu aslında
    hoş bir tesadüf: AbstractUser.is_active zaten Django'nun kendi login
    kontrolünde kullandığı "bu hesap girebilir mi" bayrağı - BaseModel'in
    "bu satır soft-delete edilmemiş mi" bayrağıyla anlam olarak zaten
    örtüşüyor, yani iki ayrı is_active tutmak yerine TEK alanı ikisi için de
    kullanmak bilinçli bir basitleştirme, sadece clash'i susturan bir hack
    değil: bir operatör deactivate edildiğinde hem "listelerde pasif
    görünür" hem "artık giriş yapamaz" aynı anda ve otomatik oluyor.

    objects AŞAĞIDA AYNI SEBEPLE YENİDEN TANIMLANDI - bkz. OperatorManager
    docstring'i (bu, is_active'in alan versiyonu değil, manager versiyonu
    olan ikinci bir clash).
    """
    ROLE_ADMIN = "admin"
    ROLE_OPERATOR = "operator"
    ROLE_CHOICES = [
        (ROLE_ADMIN, "Admin"),
        (ROLE_OPERATOR, "Operator"),
    ]

    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default=ROLE_OPERATOR)
    phone = models.CharField(max_length=30, null=True, blank=True)
    is_active = models.BooleanField(default=True, db_default=True)

    objects = OperatorManager()

    class Meta:
        db_table = "operators"

    def __str__(self):
        return self.get_full_name() or self.username


class AuditLog(BaseModel):
    """Sistemdeki her anlamlı değişiklik (kart/employee/device/firmware) için
    bir satır - "kim, ne zaman, ne yaptı" sorusuna cevap veriyor. Artık
    core/audit_viewset.py'deki AuditedModelViewSet sayesinde her CRUD
    işleminde OTOMATİK yazılıyor (ayrıca `details.changes` altında her
    değişen alanın eski/yeni değeri) - önceden sadece view'ların elle
    çağırdığı log_action()'a bağlıydı, artık unutmak mümkün değil; özel
    @action'lar (device.command, card.onboard/assign/revoke, firmware.upload
    gibi standart create/update/delete kalıbına uymayanlar) hâlâ elle
    log_action() çağırıyor.

    `operator` nullable: frontend henüz kimlik bilgisi göndermeden yapılan
    bir istek, ya da gerçekten sistem tetikli bir aksiyon, hiçbir operatöre
    atfedilemez - bunlar sessizce düşürülmek ya da sahte bir kullanıcıya
    bağlanmak yerine "system" olarak gösteriliyor.

    NOT: BaseModel'den gelen created_by, `operator` ile AYNI değeri taşıyor
    (accounts/audit.py log_action() ikisini de aynı anda, açıkça set ediyor
    - kendiliğinden olan bir şey değil, AuditLog.objects.create() BaseModel'in
    hiçbir otomatik actor-atama mekanizmasından geçmiyor). İki ayrı FK'nin
    aynı şeyi tutması istenmeyen bir tutarsızlık gibi görünebilir, ama
    `operator` bu modelin asıl, isimlendirilmiş alanı ve tüm mevcut kod
    (__str__, audit.py, frontend) onu kullanıyor; created_by sadece
    BaseModel'i istisnasız uygulamanın getirdiği, zararsız bir fazlalık.
    """
    operator = models.ForeignKey(
        Operator, null=True, blank=True, on_delete=models.SET_NULL, related_name="audit_logs"
    )
    action = models.CharField(max_length=100)
    target_repr = models.CharField(max_length=255, blank=True)
    details = models.JSONField(null=True, blank=True)

    class Meta:
        db_table = "audit_logs"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["action"]),
            models.Index(fields=["created_at"]),
        ]

    def __str__(self):
        who = self.operator.username if self.operator else "system"
        return f"{who} {self.action} {self.target_repr}".strip()
