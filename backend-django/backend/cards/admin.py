from django.contrib import admin

from cards.models import Employee, Card


@admin.register(Employee)
class EmployeeAdmin(admin.ModelAdmin):
    list_display = ["id", "full_name", "department", "employee_no", "is_active"]
    search_fields = ["full_name", "employee_no", "email"]
    list_filter = ["is_active", "department"]


@admin.register(Card)
class CardAdmin(admin.ModelAdmin):
    list_display = ["uid", "employee", "is_active", "valid_from", "valid_to"]
    search_fields = ["uid", "employee__full_name"]
    list_filter = ["is_active"]
    autocomplete_fields = ["employee"]
