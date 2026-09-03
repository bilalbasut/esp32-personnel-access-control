from django.db import models

from core.models import TimestampedModel, ActivatableModel


class Employee(TimestampedModel, ActivatableModel):
    full_name = models.CharField(max_length=255, null=True, blank=True)
    department = models.CharField(max_length=100, null=True, blank=True)

    class Meta:
        db_table = "employees"


class Card(TimestampedModel, ActivatableModel):
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
