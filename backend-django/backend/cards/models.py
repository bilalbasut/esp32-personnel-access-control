from django.db import models

from core.models import ExternallyManagedModel


class Employee(ExternallyManagedModel):
    ad_soyad = models.CharField(max_length=255, null=True, blank=True)
    departman = models.CharField(max_length=100, null=True, blank=True)
    aktif = models.SmallIntegerField(default=1)

    class Meta(ExternallyManagedModel.Meta):
        db_table = "employees"


class Card(ExternallyManagedModel):
    uid = models.CharField(max_length=50, primary_key=True)
    employee = models.ForeignKey(
        Employee, null=True, blank=True, on_delete=models.SET_NULL,
        db_column="employee_id", related_name="cards"
    )
    floors = models.CharField(max_length=100, null=True, blank=True)
    valid_from = models.BigIntegerField(null=True, blank=True)
    valid_to = models.BigIntegerField(null=True, blank=True)
    win_start_m = models.SmallIntegerField(default=0)
    win_end_m = models.SmallIntegerField(default=1440)
    aktif = models.SmallIntegerField(default=1)

    class Meta(ExternallyManagedModel.Meta):
        db_table = "cards"