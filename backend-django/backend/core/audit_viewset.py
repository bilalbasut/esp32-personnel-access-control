"""Ortak CRUD+audit mixin: created_by/updated_by/deleted_by set eder ve alan-bazlı
diff'i AuditLog'a yazar. CRUD dışı @action'lar (command, onboard, upload...) kapsam
dışı, kendi log_action()/log_change() çağrılarını elle yapar."""
from django.forms.models import model_to_dict

from accounts.audit import log_action

_JSON_SAFE_SCALARS = (str, int, float, bool)

# snapshot()'tan hariç: updated_at her save()'de yenilendiği için dahil edilirse
# hiçbir alan değişmese bile diff dolu görünür, "no-op update -> log yok" kuralını bozar.
_BOOKKEEPING_FIELDS = frozenset({
    "created_at", "updated_at", "deleted_at",
    "created_by", "updated_by", "deleted_by",
    "password",  # Operator.password - hash'i bile audit log'a yazılmasın
})


def snapshot(instance):
    """Instance'ı JSON-serializable dict'e çevirir (diff için) - non-JSON tipler str()'e çevrilir, bookkeeping alanları hariç."""
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
    """AuditLog'a alan-bazlı diff yazar. `before` yoksa (create) her dolu alan None->değer;
    varsa sadece gerçekten değişenler - update'te değişiklik yoksa hiç log yazılmaz."""
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
    """`class Foo(AuditedModelViewSet, viewsets.ModelViewSet)` sırası MRO'yu bu sınıfın
    perform_*'ını önce çalıştırır. Yan etkili ViewSet'ler (örn. Card'ın ACL republish'i)
    kendi perform_x'ini `super().perform_x()` ile çağırmalı, tam override etmemeli."""
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
