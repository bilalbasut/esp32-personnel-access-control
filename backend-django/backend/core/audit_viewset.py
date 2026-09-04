"""Her ModelViewSet'in perform_create/update/destroy'unu ayrı ayrı elle
yazıp içine log_action() çağrısı serpiştirmek yerine, BaseModel kullanan
(artık İSTİSNASIZ her model) bir kaynak için ORTAK bir CRUD+audit kalıbı:
created_by/updated_by/deleted_by'ı otomatik set eder VE her değişikliği
(alan bazlı eski/yeni değer diff'iyle) AuditLog'a otomatik yazar - bir
view'ın bunu çağırmayı unutması artık mümkün değil, gelecekte eklenecek bir
ViewSet de sadece bu mixin'i miras alarak aynı garantiyi bedava alır.

Standart create/update/destroy DIŞINDAKİ özel @action'lar (device.command,
card.onboard/assign/revoke, firmware.upload gibi) bu mixin'in kapsamı
dışında kalır - onların "action" ismi ve payload'ı zaten CRUD'dan farklı,
generic bir create/update/delete kalıbına oturmuyor; onlar hâlâ kendi
log_action() çağrılarını (ya da aşağıdaki log_change() yardımcısını)
elle yapıyor.
"""
from django.forms.models import model_to_dict

from accounts.audit import log_action

_JSON_SAFE_SCALARS = (str, int, float, bool)

# BaseModel'in kendi bookkeeping alanları (core/models.py) - snapshot()'tan
# BİLEREK ÇIKARILDI. İki ayrı, gerçek bir bug'a yol açan sebep var:
#   1. updated_at HER save()'de yenileniyor (BaseModel.save() override'ı) -
#      diff hesabına dahil edilirse, hiçbir alan fiilen değişmese bile
#      before/after'ta "updated_at değişti" görünür, bu da log_change()'in
#      "gerçek değişiklik yoksa hiçbir satır yazma" kuralını (aşağıya bkz.)
#      HER ZAMAN atlatır - "no-op update" diye bir şey kalmaz, her PATCH
#      gürültülü bir audit satırı yazar.
#   2. created_by/updated_by/deleted_by zaten AuditLog satırının kendi
#      üstünde ayrı ayrı görünür bilgi (entry.operator, ve şimdi
#      entry.created_by - bkz. accounts/audit.py log_action()) - bunları
#      details.changes içinde TEKRAR göstermek hem gereksiz gürültü hem de
#      (1) ile aynı "hep değişmiş gibi görünme" sorununu yaratıyor.
# Kalan asıl iş alanları (name, floors, is_active, vs.) hâlâ normal şekilde
# diff'e giriyor - sadece "bu satırı kim/ne zaman değiştirdi" bookkeeping'i
# diff'in dışında.
_BOOKKEEPING_FIELDS = frozenset({
    "created_at", "updated_at", "deleted_at",
    "created_by", "updated_by", "deleted_by",
})


def snapshot(instance):
    """Bir model instance'ının JSON-serializable alan/değer haritası - diff
    hesaplamak için. model_to_dict FK'leri zaten pk'sına indirger,
    ManyToMany/FileField'leri dışarıda bırakır; geri kalan (Decimal,
    datetime, vs.) AuditLog.details JSONField'ine güvenle yazılabilsin diye
    str()'e çevriliyor - JSON'ın zaten native desteklediği tipler
    (str/int/float/bool/None) olduğu gibi kalıyor. BaseModel'in bookkeeping
    alanları (_BOOKKEEPING_FIELDS - yukarıya bkz.) bilinçli olarak hariç
    tutuluyor."""
    raw = model_to_dict(instance)
    out = {}
    for key, value in raw.items():
        if key in _BOOKKEEPING_FIELDS:
            continue
        if value is None or isinstance(value, _JSON_SAFE_SCALARS):
            out[key] = value
        elif isinstance(value, (list, tuple)):
            out[key] = [str(v) for v in value]
        else:
            out[key] = str(value)
    return out


def log_change(request, model_label, action_suffix, instance, before=None, after=None, extra=None):
    """AuditLog'a alan-bazlı bir diff yazar. `before` verilmezse (create
    durumu) her dolu alan "None -> değer" olarak loglanır; `before` VE
    `after` verilirse (update/delete durumu) sadece gerçekten değişen
    alanlar loglanır - değişiklik yoksa (örn. bir update isteği hiçbir
    alanı fiilen değiştirmediyse) hiçbir satır yazılmaz, log gürültüsüz kalır."""
    after = after if after is not None else snapshot(instance)
    if before is None:
        changes = {k: {"old": None, "new": v} for k, v in after.items() if v not in (None, "", [])}
    else:
        changes = {k: {"old": before.get(k), "new": v} for k, v in after.items() if before.get(k) != v}

    if action_suffix == "update" and not changes:
        return

    details = {"changes": changes}
    if extra:
        details.update(extra)
    log_action(request, f"{model_label}.{action_suffix}", str(instance), details=details)


class AuditedModelViewSet:
    """viewsets.ModelViewSet ile birlikte bir mixin olarak kullanılır (bkz.
    DeviceViewSet/EmployeeViewSet/CardViewSet) - `class Foo(AuditedModelViewSet,
    viewsets.ModelViewSet)` sırasıyla, MRO'nun bu sınıfın perform_*
    metodlarını ModelViewSet'inkilerin ÖNÜNE almasını sağlıyor. Ekstra bir
    yan etkisi olan ViewSet'ler (örn. CardViewSet'in ACL yeniden yayını)
    kendi perform_create/update/destroy'unu tanımlayıp `super().perform_x(...)`
    ile bu mixin'i çağırmalı, tamamen override etmemeli - aksi halde
    created_by/updated_by/deleted_by ve audit log'u kaybeder.

    Bu mixin, üzerine kurulduğu modelin BaseModel'den geldiğini (yani
    created_by/updated_by/deleted_by alanlarının var olduğunu) varsayar -
    artık istisnasız her model öyle olduğu için ekstra bir hasattr()
    kontrolüne gerek yok.
    """
    #: AuditLog.action önekinde kullanılacak isim (örn. "device", "employee").
    #: Verilmezse queryset'in model adı küçük harfle kullanılır.
    audit_label = None

    def _audited_model_label(self):
        return self.audit_label or self.get_queryset().model.__name__.lower()

    def _actor(self):
        user = getattr(self.request, "user", None)
        return user if user is not None and getattr(user, "is_authenticated", False) else None

    def perform_create(self, serializer):
        instance = serializer.save(created_by=self._actor())
        log_change(self.request, self._audited_model_label(), "create", instance)

    def perform_update(self, serializer):
        instance = serializer.instance
        before = snapshot(instance)
        serializer.save(updated_by=self._actor())
        log_change(self.request, self._audited_model_label(), "update", instance, before=before)

    def perform_destroy(self, instance):
        before = snapshot(instance)
        instance.deleted_by = self._actor()
        instance.delete()  # BaseModel.delete() -> soft-delete (deleted_at + save())
        log_change(self.request, self._audited_model_label(), "delete", instance, before=before)
