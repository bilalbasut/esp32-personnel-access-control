from django.urls import path

from core import views

urlpatterns = [
    path("events", views.events_list),
    path("devices", views.devices_list),
    path("cards", views.cards_collection),          # GET list / POST create
    path("employees", views.employees_collection),  # GET list / POST create
    path("cards/add", views.cards_add),
    path("cards/revoke", views.cards_revoke),
    path("cards/<str:uid>/assign", views.cards_assign),
    path("cards/<str:uid>", views.cards_delete),
    path("reports/pdks", views.reports_pdks),
    path("devices/<str:device_id>/command", views.devices_command),
    path("devices/<str:device_id>/ota", views.devices_ota),
    path("firmware/upload", views.firmware_upload),
    path("firmware", views.firmware_list),
    path("dashboard/kpis", views.dashboard_kpis),
]
