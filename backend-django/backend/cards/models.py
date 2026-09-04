from django.db import models

from core.models import TimestampedModel, ActivatableModel, SoftDeletableModel


class Employee(TimestampedModel, ActivatableModel, SoftDeletableModel):
    full_name = models.CharField(max_length=255, null=True, blank=True)
    department = models.CharField(max_length=100, null=True, blank=True)
    # İK/kartvizit numarası - içerideki otomatik artan `id`'den farklı; o
    # bir DB implementasyon detayı, şirket kartında/İK sisteminde basılan şey
    # değil. Nullable, çünkü her employee onboarding anında bir tane
    # atanmış olmak zorunda değil.
    employee_no = models.CharField(max_length=50, null=True, blank=True, unique=True)
    email = models.EmailField(null=True, blank=True)
    phone = models.CharField(max_length=30, null=True, blank=True)

    class Meta:
        db_table = "employees"
        # Django, cascade-delete taraması için (örn. bir Employee gerçekten
        # hard-delete edildiğinde on_delete=SET_NULL süpürmesi) içeride
        # varsayılan değil *base* manager'ı kullanır. Bu filtrelenmiş
        # ActiveManager olarak kalsaydı, hard delete zaten soft-delete
        # edilmiş ama hâlâ bu satıra işaret eden Card'ları gözden
        # kaçırabilirdi. Bu yüzden filtrelenmemiş manager'a yönlendirildi ki
        # cascade her zaman her şeyi görsün; `objects` (default manager) ise
        # normal uygulama kodu için filtreli kalıyor.
        base_manager_name = "all_objects"


class Card(TimestampedModel, ActivatableModel, SoftDeletableModel):
    uid = models.CharField(max_length=50, primary_key=True)
    employee = models.ForeignKey(
        Employee, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="cards"
    )
    floors = models.CharField(max_length=100, null=True, blank=True)
    valid_from = models.BigIntegerField(null=True, blank=True)
    valid_to = models.BigIntegerField(null=True, blank=True)
    win_start_m = models.SmallIntegerField(default=0)
    win_end_m = models.SmallIntegerField(default=1440)

    class Meta:
        db_table = "cards"
        base_manager_name = "all_objects"  # neden, bkz. Employee.Meta

    def delete(self, *args, **kwargs):
        # is_active, canlı ACL binary buffer'ını besliyor (core/acl.py
        # sadece is_active=True olan kartları dahil ediyor) - silinen bir
        # kart, deleted_at'in bir şekilde fark edilmesini beklemeden erişim
        # vermeyi ANINDA durdurmalı.
        self.is_active = False
        super().delete(*args, **kwargs)
