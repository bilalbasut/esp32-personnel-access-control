from django.db import models

from core.models import BaseModel


class Employee(BaseModel):
    full_name = models.CharField(max_length=255, null=True, blank=True)
    department = models.CharField(max_length=100, null=True, blank=True)
    employee_no = models.CharField(max_length=50, null=True, blank=True, unique=True)  # İK numarası, `id`'den farklı
    email = models.EmailField(null=True, blank=True)
    phone = models.CharField(max_length=30, null=True, blank=True)

    class Meta:
        db_table = "employees"
        # Cascade-delete taraması filtrelenmemiş manager kullanmalı, yoksa soft-deleted Card'ları gözden kaçırır.
        base_manager_name = "all_objects"

    def __str__(self):
        return f"{self.full_name} (#{self.pk})" if self.full_name else f"Employee #{self.pk}"


class Card(BaseModel):
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
        self.is_active = False  # ACL buffer sadece is_active=True kartları içerir, erişim anında kesilsin
        super().delete(*args, **kwargs)

    def __str__(self):
        return self.uid
