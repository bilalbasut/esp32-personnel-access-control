from django.db import models
from core.models import TimeStampedModel

class Card(TimeStampedModel):
    uid = models.CharField(max_length=50, unique=True)
    employee_name = models.CharField(max_length=150)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.employee_name} - {self.uid}"

class Permission(TimeStampedModel):
    card = models.ForeignKey(Card, on_delete=models.CASCADE, related_name='permissions')
    access_zone = models.CharField(max_length=100)
    granted = models.BooleanField(default=True)