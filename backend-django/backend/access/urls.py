from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import CardViewSet

router = DefaultRouter()
# Automatically generates /cards/, /cards/{pk}/, /cards/{pk}/deactivate/, /cards/{pk}/scan/
router.register(r'cards', CardViewSet, basename='card')

urlpatterns = [
    path('', include(router.urls)),
]