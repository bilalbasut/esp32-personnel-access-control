from django.db import models

from core.models import TimestampedModel, ActivatableModel, SoftDeletableModel


class Employee(TimestampedModel, ActivatableModel, SoftDeletableModel):
    full_name = models.CharField(max_length=255, null=True, blank=True)
    department = models.CharField(max_length=100, null=True, blank=True)
    # HR/badge number - distinct from the internal auto-increment `id`,
    # which is a DB implementation detail and not what a company badge or
    # HR system would print/reference. Nullable since not every employee
    # necessarily has one assigned at onboarding time.
    employee_no = models.CharField(max_length=50, null=True, blank=True, unique=True)
    email = models.EmailField(null=True, blank=True)
    phone = models.CharField(max_length=30, null=True, blank=True)

    class Meta:
        db_table = "employees"
        # Django uses the *base* manager (not the default one) internally
        # for cascade-delete collection (e.g. an on_delete=SET_NULL sweep
        # when an Employee is hard-deleted for real). If that stayed the
        # filtered ActiveManager, a hard delete could miss soft-deleted
        # Cards still pointing at this row. Point it at the unfiltered
        # manager so cascades always see everything; `objects` (the
        # default manager) stays filtered for normal app code.
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
        base_manager_name = "all_objects"  # see Employee.Meta for why
